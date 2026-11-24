# Label checker — evaluation report

Ground truth is hand-typed from the label photos. The expected verdict and
expected flags are computed by the matcher and the verdict rule from
`ingredients_text` alone (never from OCR output); they are listed below
for audit. Rules, aliases and thresholds are the app's own; nothing is
tuned per image. Images where no ingredients section is found are reported
with that status and n/a metrics, not as a 100% CER.

Fast mode: **off, on**. No-heading retry: **on**.

## Expected values computed from the truth text (audit)

| lang | image | expected verdict | expected flags |
|---|---|---|---|
| ar | ar/01.jpg | À vérifier | نكهات |
| ar | ar/02.jpg | À vérifier | — |
| ar | ar/03.jpg | No incompatible ingredient found in the reference | — |
| ar | ar/04.jpg | À vérifier | نكهة |
| en | en/01.jpg | À vérifier | E627; flavour; E626; E631; E630 |
| en | en/02.jpg | À vérifier | flavour |
| en | en/03.jpg | À vérifier | natural flavors |
| en | en/04.jpg | À vérifier | natural flavor |
| en | en/05.jpg | À vérifier | — |
| en | en/06.jpg | À vérifier | soy sauce; E627; E631 |
| en | en/07.jpg | No incompatible ingredient found in the reference | — |
| fr | fr/01.jpg | À vérifier | glycérol; arômes; extrait de vanille; E471 |
| fr | fr/02.jpg | No incompatible ingredient found in the reference | — |
| fr | fr/03.jpg | À vérifier | bouillon; arômes naturels |
| fr | fr/04.jpg | Incompatible ingredient detected | jambon; porc; arômes naturels; bouillon |
| zh | zh/01.jpg | À vérifier | 脂肪酸山梨醇酐酯; 脂肪酸丙二醇酯; 乳清粉; 香料 |
| zh | zh/02.jpg | À vérifier | 单双甘油脂肪酸酯; 食品用香精; 硬脂酸; 甘油 |
| zh | zh/03.jpg | À vérifier | 5'-呈味核苷酸二钠; 食用香精香料 |
| zh | zh/04.jpg | À vérifier | 食用香精 |
| zh | zh/05.jpg | À vérifier | 硬脂酰乳酸钠; 硬脂酰乳酸钙; 食用油脂制品 |
| zh | zh/06.jpg | À vérifier | 食用香精; 乳清粉 |

## Per-image results — Fast mode off

| lang | image | status | CER (content) | CER (strict) | ing. recall | ing. precision | verdict expected | verdict actual | ok | flag recall | false alarms | blocks detected | blocks kept | strategy | retry | warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | ar/01.jpg | ok | 1.56% | 3.59% | 0.789 | 0.882 | À vérifier | À vérifier | yes | 1.000 | 0 | 7 | 7 | three_pass | — | 15.51 |
| ar | ar/02.jpg | ok | 269.81% | 256.52% | 0.000 | 0.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 21 | 21 | three_pass | — | 24.80 |
| ar | ar/03.jpg | ok | 29.58% | 35.42% | 0.125 | 0.500 | No incompatible ingredient found in the reference | À vérifier | NO | 1.000 | 0 | 17 | 17 | three_pass | — | 17.85 |
| ar | ar/04.jpg | ok | 431.37% | 416.18% | 0.429 | 0.273 | À vérifier | À vérifier | yes | 1.000 | 1 | 90 | 78 | three_pass | — | 95.15 |
| en | en/01.jpg | ok | 0.19% | 5.24% | 0.162 | 0.462 | À vérifier | À vérifier | yes | 1.000 | 0 | 46 | 46 | three_pass | — | 57.10 |
| en | en/02.jpg | ok | 13.89% | 12.64% | 0.923 | 0.923 | À vérifier | À vérifier | yes | 1.000 | 0 | 27 | 25 | three_pass | — | 35.21 |
| en | en/03.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 17 | 12 | three_pass | upscale_x2:discarded:33.86s | 62.66 |
| en | en/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 44 | 37 | three_pass | — | 49.83 |
| en | en/05.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 14 | 10 | three_pass | — | 19.13 |
| en | en/06.jpg | ok | 0.95% | 0.73% | 1.000 | 1.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 86 | 77 | three_pass | — | 131.61 |
| en | en/07.jpg | ok | 0.00% | 0.46% | 1.000 | 1.000 | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | yes | 1.000 | 0 | 8 | 8 | three_pass | — | 11.77 |
| fr | fr/01.jpg | ok | 0.13% | 8.32% | 0.964 | 0.982 | À vérifier | À vérifier | yes | 1.000 | 0 | 18 | 17 | three_pass | — | 76.14 |
| fr | fr/02.jpg | ok | 0.00% | 0.00% | 1.000 | 1.000 | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | yes | 1.000 | 0 | 5 | 5 | three_pass | — | 12.18 |
| fr | fr/03.jpg | ok | 96.34% | 93.97% | 0.625 | 0.625 | À vérifier | À vérifier | yes | 1.000 | 1 | 79 | 74 | three_pass | — | 115.45 |
| fr | fr/04.jpg | ok | 75.34% | 76.95% | 0.000 | 0.000 | Incompatible ingredient detected | À vérifier | NO | 0.000 | 0 | 13 | 10 | three_pass+retry:tiled | tiled:used:23.49s | 40.72 |
| zh | zh/01.jpg | ok | 0.00% | 5.17% | 0.870 | 0.952 | À vérifier | À vérifier | yes | 1.000 | 0 | 8 | 7 | three_pass | — | 21.53 |
| zh | zh/02.jpg | ok | 38.98% | 35.81% | 0.960 | 0.828 | À vérifier | À vérifier | yes | 1.000 | 0 | 15 | 15 | three_pass | — | 34.93 |
| zh | zh/03.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 41 | 37 | three_pass | — | 61.68 |
| zh | zh/04.jpg | ok | 74.55% | 72.84% | 0.235 | 0.800 | À vérifier | À vérifier | yes | 0.000 | 0 | 47 | 39 | three_pass | — | 49.08 |
| zh | zh/05.jpg | ok | 40.00% | 40.48% | 0.667 | 1.000 | À vérifier | À vérifier | yes | 0.333 | 0 | 24 | 24 | three_pass | — | 32.84 |
| zh | zh/06.jpg | ok | 0.00% | 1.60% | 1.000 | 1.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 29 | 24 | three_pass | — | 39.74 |

## Per-language summary — Fast mode off

| language | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | 4 | 4/4 | 183.08% | 149.69% | 1 | 1 | 0.336 | 0.414 | 3/4 | 1.000 | 1 | 38.33 |
| en | 7 | 4/7 | 3.76% | 0.57% | 3 | 4 | 0.771 | 0.846 | 7/7 | 1.000 | 0 | 52.47 |
| fr | 4 | 4/4 | 42.95% | 37.73% | 2 | 2 | 0.647 | 0.652 | 3/4 | 0.750 | 1 | 61.12 |
| zh | 6 | 5/6 | 30.71% | 38.98% | 2 | 2 | 0.746 | 0.916 | 6/6 | 0.667 | 0 | 39.97 |

### Overall — Fast mode off

| scope | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL | 21 | 17/21 | 63.10% | 13.89% | 8 | 9 | 0.632 | 0.719 | 19/21 | 0.843 | 2 | 47.85 |

## Per-image results — Fast mode on

| lang | image | status | CER (content) | CER (strict) | ing. recall | ing. precision | verdict expected | verdict actual | ok | flag recall | false alarms | blocks detected | blocks kept | strategy | retry | warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | ar/01.jpg | ok | 1.56% | 3.59% | 0.789 | 0.882 | À vérifier | À vérifier | yes | 1.000 | 0 | 7 | 7 | language_first:all | — | 13.50 |
| ar | ar/02.jpg | ok | 269.81% | 256.52% | 0.000 | 0.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 21 | 21 | language_first:ar+fr | — | 12.57 |
| ar | ar/03.jpg | ok | 25.35% | 32.29% | 0.125 | 0.500 | No incompatible ingredient found in the reference | À vérifier | NO | 1.000 | 0 | 17 | 17 | language_first:ar+fr | — | 10.00 |
| ar | ar/04.jpg | ok | 431.37% | 416.18% | 0.429 | 0.273 | À vérifier | À vérifier | yes | 1.000 | 1 | 90 | 78 | language_first:ar+fr | — | 41.04 |
| en | en/01.jpg | ok | 0.19% | 5.24% | 0.162 | 0.462 | À vérifier | À vérifier | yes | 1.000 | 0 | 46 | 46 | language_first:fr | — | 18.48 |
| en | en/02.jpg | ok | 13.89% | 12.64% | 0.923 | 0.923 | À vérifier | À vérifier | yes | 1.000 | 0 | 27 | 25 | language_first:fr | — | 10.72 |
| en | en/03.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 17 | 12 | language_first:fr | upscale_x2:discarded:8.58s | 23.90 |
| en | en/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 44 | 37 | language_first:fr | — | 14.18 |
| en | en/05.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 14 | 10 | language_first:fr | — | 9.88 |
| en | en/06.jpg | ok | 0.95% | 0.73% | 1.000 | 1.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 86 | 76 | language_first:fr | — | 39.71 |
| en | en/07.jpg | ok | 0.00% | 0.46% | 1.000 | 1.000 | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | yes | 1.000 | 0 | 8 | 8 | language_first:all | — | 10.23 |
| fr | fr/01.jpg | ok | 0.13% | 8.32% | 0.964 | 0.982 | À vérifier | À vérifier | yes | 1.000 | 0 | 18 | 17 | language_first:fr | — | 32.55 |
| fr | fr/02.jpg | ok | 0.00% | 0.00% | 1.000 | 1.000 | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | yes | 1.000 | 0 | 5 | 5 | language_first:all | — | 10.93 |
| fr | fr/03.jpg | ok | 96.34% | 93.97% | 0.625 | 0.625 | À vérifier | À vérifier | yes | 1.000 | 1 | 79 | 74 | language_first:fr | — | 39.74 |
| fr | fr/04.jpg | ok | 75.34% | 76.95% | 0.000 | 0.000 | Incompatible ingredient detected | À vérifier | NO | 0.000 | 0 | 13 | 10 | language_first:all+retry:tiled | tiled:used:18.23s | 33.52 |
| zh | zh/01.jpg | ok | 0.00% | 5.17% | 0.870 | 0.952 | À vérifier | À vérifier | yes | 1.000 | 0 | 8 | 7 | language_first:all | — | 16.37 |
| zh | zh/02.jpg | ok | 38.98% | 35.81% | 0.960 | 0.828 | À vérifier | À vérifier | yes | 1.000 | 0 | 15 | 15 | language_first:zh | — | 21.86 |
| zh | zh/03.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 41 | 37 | language_first:zh | — | 28.87 |
| zh | zh/04.jpg | ok | 74.55% | 74.07% | 0.235 | 1.000 | À vérifier | À vérifier | yes | 0.000 | 0 | 47 | 30 | language_first:zh | — | 33.71 |
| zh | zh/05.jpg | ok | 40.00% | 40.48% | 0.667 | 1.000 | À vérifier | À vérifier | yes | 0.333 | 0 | 24 | 24 | language_first:fr+zh | — | 29.56 |
| zh | zh/06.jpg | ok | 0.00% | 1.60% | 1.000 | 1.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 29 | 23 | language_first:zh | — | 30.65 |

## Per-language summary — Fast mode on

| language | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | 4 | 4/4 | 182.02% | 147.58% | 1 | 1 | 0.336 | 0.414 | 3/4 | 1.000 | 1 | 19.28 |
| en | 7 | 4/7 | 3.76% | 0.57% | 3 | 4 | 0.771 | 0.846 | 7/7 | 1.000 | 0 | 18.16 |
| fr | 4 | 4/4 | 42.95% | 37.73% | 2 | 2 | 0.647 | 0.652 | 3/4 | 0.750 | 1 | 29.19 |
| zh | 6 | 5/6 | 30.71% | 38.98% | 2 | 2 | 0.746 | 0.956 | 6/6 | 0.667 | 0 | 26.84 |

### Overall — Fast mode on

| scope | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL | 21 | 17/21 | 62.85% | 13.89% | 8 | 9 | 0.632 | 0.731 | 19/21 | 0.843 | 2 | 22.95 |

## Fast mode comparison (off vs on)

Mean warm time: 47.85s off, 22.95s on (2.09x).

| image | CER off | CER on | Δ CER | recall off | recall on | Δ recall | blocks 3-pass | blocks kept | strategy (on) | warm off s | warm on s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ar/01.jpg | 1.56% | 1.56% | +0.00 pp | 0.789 | 0.789 | +0.000 | 7 | 7 | language_first:all | 15.51 | 13.50 |
| ar/02.jpg | 269.81% | 269.81% | +0.00 pp | 0.000 | 0.000 | +0.000 | 21 | 21 | language_first:ar+fr | 24.80 | 12.57 |
| ar/03.jpg | 29.58% | 25.35% | -4.23 pp | 0.125 | 0.125 | +0.000 | 17 | 17 | language_first:ar+fr | 17.85 | 10.00 |
| ar/04.jpg | 431.37% | 431.37% | +0.00 pp | 0.429 | 0.429 | +0.000 | 78 | 78 | language_first:ar+fr | 95.15 | 41.04 |
| en/01.jpg | 0.19% | 0.19% | +0.00 pp | 0.162 | 0.162 | +0.000 | 46 | 46 | language_first:fr | 57.10 | 18.48 |
| en/02.jpg | 13.89% | 13.89% | +0.00 pp | 0.923 | 0.923 | +0.000 | 25 | 25 | language_first:fr | 35.21 | 10.72 |
| en/03.jpg | — | — | — | — | — | — | 12 | 12 | language_first:fr | 62.66 | 23.90 |
| en/04.jpg | — | — | — | — | — | — | 37 | 37 | language_first:fr | 49.83 | 14.18 |
| en/05.jpg | — | — | — | — | — | — | 10 | 10 | language_first:fr | 19.13 | 9.88 |
| en/06.jpg | 0.95% | 0.95% | +0.00 pp | 1.000 | 1.000 | +0.000 | 77 | 76 | language_first:fr | 131.61 | 39.71 |
| en/07.jpg | 0.00% | 0.00% | +0.00 pp | 1.000 | 1.000 | +0.000 | 8 | 8 | language_first:all | 11.77 | 10.23 |
| fr/01.jpg | 0.13% | 0.13% | +0.00 pp | 0.964 | 0.964 | +0.000 | 17 | 17 | language_first:fr | 76.14 | 32.55 |
| fr/02.jpg | 0.00% | 0.00% | +0.00 pp | 1.000 | 1.000 | +0.000 | 5 | 5 | language_first:all | 12.18 | 10.93 |
| fr/03.jpg | 96.34% | 96.34% | +0.00 pp | 0.625 | 0.625 | +0.000 | 74 | 74 | language_first:fr | 115.45 | 39.74 |
| fr/04.jpg | 75.34% | 75.34% | +0.00 pp | 0.000 | 0.000 | +0.000 | 10 | 10 | language_first:all+retry:tiled | 40.72 | 33.52 |
| zh/01.jpg | 0.00% | 0.00% | +0.00 pp | 0.870 | 0.870 | +0.000 | 7 | 7 | language_first:all | 21.53 | 16.37 |
| zh/02.jpg | 38.98% | 38.98% | +0.00 pp | 0.960 | 0.960 | +0.000 | 15 | 15 | language_first:zh | 34.93 | 21.86 |
| zh/03.jpg | — | — | — | — | — | — | 37 | 37 | language_first:zh | 61.68 | 28.87 |
| zh/04.jpg | 74.55% | 74.55% | +0.00 pp | 0.235 | 0.235 | +0.000 | 39 | 30 | language_first:zh | 49.08 | 33.71 |
| zh/05.jpg | 40.00% | 40.00% | +0.00 pp | 0.667 | 0.667 | +0.000 | 24 | 24 | language_first:fr+zh | 32.84 | 29.56 |
| zh/06.jpg | 0.00% | 0.00% | +0.00 pp | 1.000 | 1.000 | +0.000 | 24 | 23 | language_first:zh | 39.74 | 30.65 |

## Verdict changes vs previous run

Previous results: `eval\diagnostics\results_before_section_fix.csv`.

| fast | image | old verdict | new verdict | changed |
|---|---|---|---|---|
| off | ar/01.jpg | À vérifier | À vérifier | — |
| off | ar/02.jpg | No incompatible ingredient found in the reference | À vérifier | yes |
| off | ar/03.jpg | No incompatible ingredient found in the reference | À vérifier | yes |
| off | ar/04.jpg | À vérifier | À vérifier | — |
| off | en/01.jpg | À vérifier | À vérifier | — |
| off | en/02.jpg | À vérifier | À vérifier | — |
| off | en/03.jpg | À vérifier | À vérifier | — |
| off | en/04.jpg | À vérifier | À vérifier | — |
| off | en/05.jpg | À vérifier | À vérifier | — |
| off | en/06.jpg | À vérifier | À vérifier | — |
| off | fr/01.jpg | À vérifier | À vérifier | — |
| off | fr/02.jpg | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | — |
| off | fr/03.jpg | À vérifier | À vérifier | — |
| off | fr/04.jpg | À vérifier | À vérifier | — |
| off | zh/01.jpg | À vérifier | À vérifier | — |
| off | zh/02.jpg | À vérifier | À vérifier | — |
| off | zh/03.jpg | À vérifier | À vérifier | — |
| off | zh/04.jpg | À vérifier | À vérifier | — |
| off | zh/05.jpg | À vérifier | À vérifier | — |
| on | ar/01.jpg | À vérifier | À vérifier | — |
| on | ar/02.jpg | No incompatible ingredient found in the reference | À vérifier | yes |
| on | ar/03.jpg | No incompatible ingredient found in the reference | À vérifier | yes |
| on | ar/04.jpg | À vérifier | À vérifier | — |
| on | en/01.jpg | À vérifier | À vérifier | — |
| on | en/02.jpg | À vérifier | À vérifier | — |
| on | en/03.jpg | À vérifier | À vérifier | — |
| on | en/04.jpg | À vérifier | À vérifier | — |
| on | en/05.jpg | À vérifier | À vérifier | — |
| on | en/06.jpg | À vérifier | À vérifier | — |
| on | fr/01.jpg | À vérifier | À vérifier | — |
| on | fr/02.jpg | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | — |
| on | fr/03.jpg | À vérifier | À vérifier | — |
| on | fr/04.jpg | À vérifier | À vérifier | — |
| on | zh/01.jpg | À vérifier | À vérifier | — |
| on | zh/02.jpg | À vérifier | À vérifier | — |
| on | zh/03.jpg | À vérifier | À vérifier | — |
| on | zh/04.jpg | À vérifier | À vérifier | — |
| on | zh/05.jpg | À vérifier | À vérifier | — |

## Observations / suspected bugs

Listed, not fixed (evaluation is read-only).

- ar: only 4 image(s) available (target was 5); add eval/ar/NN.jpg + NN.truth.json to extend the eval
- fr: only 4 image(s) available (target was 5); add eval/fr/NN.jpg + NN.truth.json to extend the eval
- [fast off] ar/01.jpg: unrecognized ingredients: ['حمض الستريكمادة حافة', 'قصب السكر']
- [fast off] ar/02.jpg: content CER 269.81% above the 3% target
- [fast off] ar/02.jpg: unrecognized ingredients: ['Matière grasse', 'amidon ferments lactiques. المادة الدسمة ٪ لا يحتوي علي الغلوتين', 'خمائر lait frais entier']
- [fast off] ar/02.jpg: 2 products detected; verdict aggregated by severity (worst case)
- [fast off] ar/03.jpg: verdict mismatch — expected 'No incompatible ingredient found in the reference', got 'À vérifier'
- [fast off] ar/03.jpg: content CER 29.58% above the 3% target
- [fast off] ar/03.jpg: unrecognized ingredients: ['e224', 'e330', 'الاكسدة', 'الخريل', 'المايدة', 'حافظة', 'حبات', 'خل', 'ماء', 'مادة', 'ومضاد']
- [fast off] ar/04.jpg: false-alarm flags: ['arome naturel', 'arômes naturels', 'natural flavors', 'vitamine arôme naturel. de production = date de péremption', 'نكهات طبيعية', '天然香料']
- [fast off] ar/04.jpg: content CER 431.37% above the 3% target
- [fast off] ar/04.jpg: unrecognized ingredients: ["30 jours. voir au dessus de l'emballage. Agiter avant de servir", 'محمض حامض الليمون']
- [fast off] ar/04.jpg: 13 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] ar/04.jpg: 2 products detected; verdict aggregated by severity (worst case)
- [fast off] en/01.jpg: characters read correctly (content CER 0.19%) but ingredient recall collapsed (0.162) — OCR returned the section without the label's separators (commas), so split_ingredients sees fused runs of several ingredients per segment; suspected OCR separator loss, listed here instead of fixed
- [fast off] en/01.jpg: 3 products detected; verdict aggregated by severity (worst case)
- [fast off] en/02.jpg: content CER 13.89% above the 3% target
- [fast off] en/02.jpg: unrecognized ingredients: ['Lb. bulgaricus', 'blueberries', 'live lactic cultures  SC. thermophilus']
- [fast off] en/02.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/03.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] en/03.jpg: 13 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/03.jpg: no heading on the first pass; upscale_x2 retry discarded (33.86s, blocks 12 -> 12)
- [fast off] en/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] en/04.jpg: 7 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/05.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] en/05.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/06.jpg: unrecognized ingredients: ['DRIED MUSHROOM', 'KELP', 'MUSHROOM', 'NOODLES', 'SEASONING']
- [fast off] en/06.jpg: 10 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/01.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/03.jpg: false-alarm flags: ['ham, bacon and cured pork products', 'jambon', 'jambon, bacon, lardons', "moins d'eau qu'une tranche de jambon. Sans gluten. Une allergie", 'لحم مقدد / بيكون / هام', '火腿']
- [fast off] fr/03.jpg: content CER 96.34% above the 3% target
- [fast off] fr/03.jpg: unrecognized ingredients: ['Dignons', 'Valeurs Pour Par', 'au final', 'extrait de plantes', 'nous avons besoin beaucoup pour cuisiner les flashant corail afin obtenir une tranche delicieuse qui contient', 'plantes aromatiques RETROUVEZ DES céleri', 'une intolérance']
- [fast off] fr/03.jpg: 5 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/04.jpg: verdict mismatch — expected 'Incompatible ingredient detected', got 'À vérifier'
- [fast off] fr/04.jpg: expected flags not raised: ['jambon', 'porc', 'arômes naturels', 'bouillon']
- [fast off] fr/04.jpg: content CER 75.34% above the 3% target
- [fast off] fr/04.jpg: unrecognized ingredients: ['a plants romaqu Su ChorureptoxydaAderqeiagroudre. poudre', 'ponqvàroan couener']
- [fast off] fr/04.jpg: 12 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/04.jpg: no heading on the first pass; tiled retry kept (23.49s, blocks 4 -> 10)
- [fast off] zh/01.jpg: 1 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] zh/02.jpg: content CER 38.98% above the 3% target
- [fast off] zh/02.jpg: unrecognized ingredients: ['GB', 'gb', 'sc12413052801630', '丙二醇', '二氢二钠', '产品标准', '复配', '山梨醇酐单', '生产日期', '生活', '脱氢乙酸钠', '见包装打码', '食品生产许可证编号']
- [fast off] zh/03.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] zh/03.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] zh/04.jpg: expected flags not raised: ['食用香精']
- [fast off] zh/04.jpg: content CER 74.55% above the 3% target
- [fast off] zh/04.jpg: unrecognized ingredients: ['gb19640', '脆片']
- [fast off] zh/04.jpg: 9 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] zh/05.jpg: expected flags not raised: ['硬脂酰乳酸钠', '硬脂酰乳酸钙']
- [fast off] zh/05.jpg: content CER 40.00% above the 3% target
- [fast off] zh/05.jpg: unrecognized ingredients: ['脱氢乙酸钠']
- [fast off] zh/06.jpg: 5 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] ar/01.jpg: unrecognized ingredients: ['حمض الستريكمادة حافة', 'قصب السكر']
- [fast on] ar/02.jpg: content CER 269.81% above the 3% target
- [fast on] ar/02.jpg: unrecognized ingredients: ['Matière grasse', 'amidon ferments lactiques. المادة الدسمة ٪ لا يحتوي علي الغلوتين', 'خمائر lait frais entier']
- [fast on] ar/02.jpg: 2 products detected; verdict aggregated by severity (worst case)
- [fast on] ar/03.jpg: verdict mismatch — expected 'No incompatible ingredient found in the reference', got 'À vérifier'
- [fast on] ar/03.jpg: content CER 25.35% above the 3% target
- [fast on] ar/03.jpg: unrecognized ingredients: ['حبات الخريل المايدة ومضاد']
- [fast on] ar/04.jpg: false-alarm flags: ['arome naturel', 'arômes naturels', 'natural flavors', 'vitamine arôme naturel. de production = date de péremption', 'نكهات طبيعية', '天然香料']
- [fast on] ar/04.jpg: content CER 431.37% above the 3% target
- [fast on] ar/04.jpg: unrecognized ingredients: ["30 jours. voir au dessus de l'emballage. Agiter avant de servir", 'محمض حامض الليمون']
- [fast on] ar/04.jpg: 13 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] ar/04.jpg: 2 products detected; verdict aggregated by severity (worst case)
- [fast on] en/01.jpg: characters read correctly (content CER 0.19%) but ingredient recall collapsed (0.162) — OCR returned the section without the label's separators (commas), so split_ingredients sees fused runs of several ingredients per segment; suspected OCR separator loss, listed here instead of fixed
- [fast on] en/01.jpg: 3 products detected; verdict aggregated by severity (worst case)
- [fast on] en/02.jpg: content CER 13.89% above the 3% target
- [fast on] en/02.jpg: unrecognized ingredients: ['Lb. bulgaricus', 'blueberries', 'live lactic cultures  SC. thermophilus']
- [fast on] en/02.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/03.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] en/03.jpg: 13 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/03.jpg: no heading on the first pass; upscale_x2 retry discarded (8.58s, blocks 12 -> 12)
- [fast on] en/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] en/04.jpg: 7 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/05.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] en/05.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/06.jpg: unrecognized ingredients: ['DRIED MUSHROOM', 'KELP', 'MUSHROOM', 'NOODLES', 'SEASONING']
- [fast on] en/06.jpg: 10 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/01.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/03.jpg: false-alarm flags: ['ham, bacon and cured pork products', 'jambon', 'jambon, bacon, lardons', "moins d'eau qu'une tranche de jambon. Sans gluten. Une allergie", 'لحم مقدد / بيكون / هام', '火腿']
- [fast on] fr/03.jpg: content CER 96.34% above the 3% target
- [fast on] fr/03.jpg: unrecognized ingredients: ['Dignons', 'Valeurs Pour Par', 'au final', 'extrait de plantes', 'nous avons besoin beaucoup pour cuisiner les flashant corail afin obtenir une tranche delicieuse qui contient', 'plantes aromatiques RETROUVEZ DES céleri', 'une intolérance']
- [fast on] fr/03.jpg: 5 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/04.jpg: verdict mismatch — expected 'Incompatible ingredient detected', got 'À vérifier'
- [fast on] fr/04.jpg: expected flags not raised: ['jambon', 'porc', 'arômes naturels', 'bouillon']
- [fast on] fr/04.jpg: content CER 75.34% above the 3% target
- [fast on] fr/04.jpg: unrecognized ingredients: ['a plants romaqu Su ChorureptoxydaAderqeiagroudre. poudre', 'ponqvàroan couener']
- [fast on] fr/04.jpg: 12 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/04.jpg: no heading on the first pass; tiled retry kept (18.23s, blocks 4 -> 10)
- [fast on] zh/01.jpg: 1 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] zh/02.jpg: content CER 38.98% above the 3% target
- [fast on] zh/02.jpg: unrecognized ingredients: ['GB', 'gb', 'sc12413052801630', '丙二醇', '二氢二钠', '产品标准', '复配', '山梨醇酐单', '生产日期', '生活', '脱氢乙酸钠', '见包装打码', '食品生产许可证编号']
- [fast on] zh/03.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] zh/03.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] zh/04.jpg: expected flags not raised: ['食用香精']
- [fast on] zh/04.jpg: content CER 74.55% above the 3% target
- [fast on] zh/04.jpg: unrecognized ingredients: ['脆片']
- [fast on] zh/04.jpg: 17 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] zh/05.jpg: expected flags not raised: ['硬脂酰乳酸钠', '硬脂酰乳酸钙']
- [fast on] zh/05.jpg: content CER 40.00% above the 3% target
- [fast on] zh/05.jpg: unrecognized ingredients: ['脱氢乙酸钠']
- [fast on] zh/06.jpg: 6 block(s) unreadable or uncertain (dropped but recorded)

## Metric definitions

- CER (content): Levenshtein / reference length on punctuation-free text;
  strict CER keeps punctuation. Target <= 3%.
- Median CER (content) and the CER < 3% / CER < 15% columns are computed
  per language and overall on images with a section only; the threshold
  columns count images (no-section images are n/a and excluded).
- Ingredient recall/precision: truth and extracted section split into
  ingredients, greedy 1:1 match at rapidfuzz >= 75 (punctuation-free).
- Flags: findings with status depends_on_origin or incompatible;
  expected flags are the flags the matcher raises on the truth text;
  a flag matches on equality, containment, the same E-number, the same
  whole-word token set, or spelling similarity >= 85 (eval-side only).
- Verdict: computed from the truth text by the same rule as the app
  (incompatible > unrecognized real ingredient / depends_on_origin /
  low coverage / unreadable block in section / low confidence / empty /
  no-heading > clear).
- Unrecognized real ingredients force "À vérifier" with reason
  "Not in the reference: <names>" on both the truth and OCR sides; the
  coverage guard is a secondary reason only.
- Warm time: models preloaded once, one warmup run discarded per mode.
- Blocks detected/kept: text boxes from detection vs OCRResult blocks
  kept after script/confidence filtering (one per box in 3-pass mode).
- Status: "no ingredients section found" when no ingredients heading is
  read. CER, recall, precision and flag recall are n/a for those images
  and excluded from the averages (never shown as CER 100%).
- Retry: tiled (aspect ratio > 3) or upscale_x2 (long side < 800 px) is
  attempted only when the first pass finds no ingredients heading; its
  results replace the first pass only if a heading appears.
