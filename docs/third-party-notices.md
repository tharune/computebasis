# Third-party notices

## Local land geometry

The map packages simplified land geometry from Natural Earth 1:110m data.
Natural Earth places its vector and raster datasets in the public domain and
permits commercial use and modification under its [terms of use](https://www.naturalearthdata.com/about/terms-of-use/).
Only land geometry is retained; no live position, source price, site identifier
or user record is part of that asset. It is served locally without external tiles.

Made with Natural Earth. [Dataset repository](https://github.com/nvkelso/natural-earth-vector).

## US state outlines and projection

The US capacity map draws state outlines from `us-atlas` 3.0.1 (`states-albers-10m`), which redistributes the US Census Bureau's cartographic
boundary files, 2017 edition, already projected for a 975 by 610 frame. The boundaries are US government data and are in the public domain
([source](https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html)). `us-atlas` is licensed under the ISC license.
The outlines were converted offline to SVG paths rounded to a tenth of a unit, with rings under 0.6 square units and the far Aleutians dropped;
only `us-states.js` is kept. The map's `project(lat, lon)` re-implements the Albers conic equal-area projection with the parameters and inset
placement of `d3-geo`'s `geoAlbersUsa` (ISC), and was checked against it point for point.

```text
Copyright 2013-2019 Michael Bostock (us-atlas)
Copyright 2010-2024 Mike Bostock (d3-geo)

Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.
```

No site, price, position or user record is part of that asset. It is served locally; the map makes no external request.

## Number-format and date compatibility

The read-only OOXML reader's built-in number formats and Excel serial-date
compatibility behavior follow openpyxl 3.1.5. The following notice accompanies
those portions. The bounded archive, lineage and schema-neutral extraction
interfaces have their own validation; this notice is not a compatibility or
security certification.

```text
Copyright (c) 2010 openpyxl

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

Energinet Energi Data Service provides DayAheadPrices under CC BY 4.0. Live records stay in local runtime storage. The adapter normalizes documented UTC timestamps, signed EUR/DKK rates and bounded delivery intervals; retain source attribution and disclose those transformations. See https://www.energidataservice.dk/terms-and-conditions.

## Geist typeface

The workbench and landing page set their text in Geist, copyright 2024 The Geist
Project Authors, licensed under the SIL Open Font License 1.1. The file served
from `src/compute_pricing/control/workbench/assets/fonts/` is a Latin subset of
the variable font (weights 400 to 700, plus arrows, minus and comparison signs).
The license text accompanies it in `OFL-Geist.txt`. The font is served locally;
no font request leaves the machine.
