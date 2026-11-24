# Institution logos

Official artwork of the authors' institutions, shown in the page header in
affiliation order. Every file is stored exactly as it was served: no
redrawing, recolouring, cropping or re-encoding. The page shows each one
through `<img>` at one uniform height and, in the dark theme, on a light chip.
The marks belong to their institutions.

Retrieved on 2026-11-24 with plain GET requests.

| File | Institution | Retrieved from | SHA-256 of the stored file |
|---|---|---|---|
| `zhejiang-university.svg` | Zhejiang University (horizontal wordmark) | `https://aim-uofa.github.io/STAIR/logos/zju-horizontal.svg` | `c9531c802dcef3e93822d04079ec333e59f93eb4ec39c668fb2d185d9313b1ba` |
| `zhongguancun-academy.png` | Zhongguancun Academy | `https://www.bza.edu.cn/adminapi/public/default/logo.png` (header logo of `https://www.bza.edu.cn/`) | `9f796ca9c2651c82c9abfc91dab31c7fa2b0951fcd0fd9a105f21691546a8c3e` |
| `lanzhou-university.svg` | Lanzhou University (seal) | `https://upload.wikimedia.org/wikipedia/en/b/be/Lanzhou_University_logo.svg` (the logo file of the English Wikipedia article on the university, which credits `http://en.lzu.edu.cn`) | `ef80ffe3324379279a1b662bda4ae901bb019e51b4cba0e7e48dddc6c3b1e8af` |
| `institute-of-automation-cas.jpg` | Institute of Automation, Chinese Academy of Sciences | `http://english.ia.cas.cn/images/iacas_logo.jpg` (header logo of `http://english.ia.cas.cn/`) | `3fe407a2979241ecc52a8cef0ce5ccd79d74e97b1341f0088b65215cc357265e` |

Notes

- `zhejiang-university.svg` holds only `svg`, `g` and `path` elements: no
  script, no event attribute, no link, no external reference and no embedded
  image, so nothing had to be removed. It is byte-identical to the served
  file.
- `institute-of-automation-cas.jpg` has a white ground; the header band is
  white in the light theme and the chip is white in the dark theme.
- `lanzhou-university.svg`: the university's own site answers plain requests with a script
  challenge, so the file comes from the English Wikipedia, where it is hosted as the
  university's logo under fair use. It holds only `svg`, `g` and `path` elements and is
  byte-identical to the served file. It is a round seal, so it is shown a little taller
  than the wordmarks (`logo_height` in `data/site.json`).
