"""Invented connector security cases; no API calls or real source payloads."""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compute_pricing.control.connectors import ConnectorError, SourcePolicy, load_policies
from compute_pricing.control.connectors.adapters import parse_ecb
from compute_pricing.control.connectors.transport import RawResponse, ReadRequest, SOURCE_SPECS


ENVELOPE = '''<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
 <Cube><Cube time="2026-10-13"><Cube currency="USD" rate="1.234567890123456789012345678901"/></Cube></Cube>
</gesmes:Envelope>'''


def ecb_policy():
    return SourcePolicy("ecb", enabled=True, rights_status="allowed", rights_evidence="invented-review",
        permissions={"observe": "PASS", "retain": "PASS", "benchmark": "PASS", "execution": "FAIL"},
        verified_by="invented-reviewer", max_age_s=604800)


def raw(body):
    return RawResponse("ecb", "2026-10-14T12:00:00Z", "/stats/eurofxref/eurofxref-daily.xml", 200, {}, body)


class XMLHardeningTests(unittest.TestCase):
    def test_internal_entities_refused_in_utf8_utf16_and_big_endian(self):
        document = ENVELOPE.replace('<?xml version="1.0" encoding="UTF-8"?>',
            '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE gesmes:Envelope [<!ENTITY invented "999">]>')
        document = document.replace('rate="1.234567890123456789012345678901"', 'rate="&invented;"')
        encodings = (document.encode("utf-8"), document.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16"),
            b"\xfe\xff" + document.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16-be"))
        for body in encodings:
            with self.subTest(encoding=body[:8]), self.assertRaisesRegex(ConnectorError, "ecb_xml_resource_or_entity_forbidden"):
                parse_ecb(raw(body), ecb_policy())

    def test_external_and_empty_doctypes_refused_before_resolution(self):
        for declaration in ('<!DOCTYPE gesmes:Envelope SYSTEM "https://invalid.example/never-requested">',
                            '<!DOCTYPE gesmes:Envelope>'):
            document = ENVELOPE.replace('?>', '?>' + declaration, 1)
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ConnectorError, "ecb_xml_resource_or_entity_forbidden"):
                parse_ecb(raw(document.encode()), ecb_policy())

    def test_declaration_after_large_comment_is_still_refused(self):
        declaration = '<!--' + 'invented-padding' * 2000 + '--><!DOCTYPE gesmes:Envelope>'
        document = ENVELOPE.replace('?>', '?>' + declaration, 1)
        with self.assertRaisesRegex(ConnectorError, "ecb_xml_resource_or_entity_forbidden"):
            parse_ecb(raw(document.encode()), ecb_policy())

    def test_benign_utf16_is_exact_informational_data(self):
        body = ENVELOPE.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
        batch = parse_ecb(raw(body), ecb_policy())
        self.assertEqual(batch.catalog_records[0]["quote_per_base"], "1.234567890123456789012345678901")
        self.assertFalse(batch.catalog_records[0]["transaction_quote"])
        self.assertEqual(batch.observations, ())

    def test_wrong_envelope_and_hidden_period_are_not_complete_daily_files(self):
        wrong = ENVELOPE.replace('gesmes:Envelope', 'gesmes:Invented')
        hidden = ENVELOPE.replace('<Cube><Cube time=', '<Invented><Cube><Cube time=').replace('</Cube></Cube>', '</Cube></Cube></Invented>')
        for document in (wrong, hidden):
            with self.subTest(document=document[:100]), self.assertRaises(ConnectorError):
                parse_ecb(raw(document.encode()), ecb_policy())

    def test_multiple_periods_unrecognized_children_and_nested_rates_refused(self):
        period = '<Cube time="2026-10-12"><Cube currency="ZZZ" rate="2"/></Cube>'
        multiple = ENVELOPE.replace('</Cube></Cube>', '</Cube>' + period + '</Cube>')
        unexpected = ENVELOPE.replace('</Cube></Cube>', '<Invented currency="ZZZ" rate="2"/></Cube></Cube>')
        nested = ENVELOPE.replace('rate="1.234567890123456789012345678901"/>', 'rate="1"><Cube currency="ZZZ" rate="2"/></Cube>')
        for document in (multiple, unexpected, nested):
            with self.subTest(document=document[-150:]), self.assertRaises(ConnectorError):
                parse_ecb(raw(document.encode()), ecb_policy())

    def test_malformed_and_oversized_xml_return_safe_codes(self):
        for body in (b'<private invented-marker="never-echo-this"', b'x' * (256 * 1024 + 1)):
            with self.subTest(size=len(body)), self.assertRaises(ConnectorError) as caught:
                parse_ecb(raw(body), ecb_policy())
            self.assertNotIn("never-echo-this", str(caught.exception))


class AdmissionConfigHardeningTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "invented-admission.json"
            target.write_bytes(text.encode())
            return load_policies(target)

    def test_duplicate_source_and_nested_permissions_cannot_last_win(self):
        configs = (
            '{"schema":"computebasis-source-admission/1.0","sources":{},"sources":{}}',
            '{"schema":"computebasis-source-admission/1.0","sources":{"ecb":{"enabled":false,"enabled":true}}}',
            '{"schema":"computebasis-source-admission/1.0","sources":{"ecb":{"permissions":{"observe":"FAIL","observe":"PASS"}}}}',
        )
        for text in configs:
            with self.subTest(text=text), self.assertRaisesRegex(ConnectorError, "duplicate_source_config_key"):
                self.load_text(text)

    def test_nonobject_invalid_unicode_and_large_config_fail_closed(self):
        for text in ('[]', 'null', '{"schema":"computebasis-source-admission/1.0","sources":[]}', ' ' * (256 * 1024 + 1)):
            with self.subTest(size=len(text)), self.assertRaises(ConnectorError):
                self.load_text(text)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "invented-admission.json"
            target.write_bytes(b'\xffprivate-never-echo')
            with self.assertRaises(ConnectorError) as caught:
                load_policies(target)
            self.assertNotIn("private-never-echo", str(caught.exception))

    def test_registered_sources_and_rights_values_unchanged(self):
        policies = load_policies(Path(__file__).resolve().parents[1] / "examples/source-admission.json")
        self.assertEqual({name for name, policy in policies.items() if policy.enabled}, {"getdeploying", "azure", "ecb", "huggingface", "aws_public_pricing", "openrouter", "huggingface_catalog", "energinet_day_ahead", "gpuhunt_catalog"})
        for policy in policies.values():
            self.assertNotEqual(policy.permissions.get("execution"), "PASS")
        self.assertEqual(policies["ecb"].blockers("benchmark", dt.datetime(2026, 10, 14, tzinfo=dt.timezone.utc)), [])

    def test_percent_encoded_duplicate_filter_key_is_not_a_second_scope(self):
        url = "https://prices.azure.com/api/retail/prices?$filter=one&%24filter=two"
        with self.assertRaisesRegex(ConnectorError, "query_key_not_allowed"):
            ReadRequest(SOURCE_SPECS["azure"], url).validate()


if __name__ == "__main__":
    unittest.main()
