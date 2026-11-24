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
| `institute-of-automation-cas.jpg` | Institute of Automation, Chinese Academy of Sciences | `http://english.ia.cas.cn/images/iacas_logo.jpg` (header logo of `http://english.ia.cas.cn/`) | `3fe407a2979241ecc52a8cef0ce5ccd79d74e97b1341f0088b65215cc357265e` |

Notes

- `zhejiang-university.svg` holds only `svg`, `g` and `path` elements: no
  script, no event attribute, no link, no external reference and no embedded
  image, so nothing had to be removed. It is byte-identical to the served
  file.
- `institute-of-automation-cas.jpg` has a white ground; the header band is
  white in the light theme and the chip is white in the dark theme.
- Lanzhou University: no logo is shown. The university's main site answered
  plain requests with a script challenge (HTTP 412), Wikimedia Commons holds
  no logo file for it, and the files reachable on other official pages are
  lock-ups of sub-units (a school, an institute, the information-disclosure
  platform), which could only be used by cropping. To add the logo later,
  save the official file here, add a row above, and set `logo` and `logo_alt`
  for affiliation 3 in `data/site.json`.
