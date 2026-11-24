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
| ar | ar/02.jpg | À vérifier | غليسرول |
| ar | ar/03.jpg | À vérifier | — |
| ar | ar/04.jpg | À vérifier | نكهة; E322 |
| ar | ar/05.jpg | À vérifier | نكهة |
| en | en/01.jpg | À vérifier | soy sauce; natural flavors; disodium guanylate; disodium inosinate; chicken |
| en | en/02.jpg | À vérifier | lecithins |
| en | en/03.jpg | À vérifier | whey powder; flavouring |
| en | en/04.jpg | À vérifier | flavor |
| en | en/05.jpg | À vérifier | flavouring |
| fr | fr/01.jpg | Incompatible ingredient detected | porc; arome naturel |
| fr | fr/02.jpg | No incompatible ingredient found in the reference | — |
| fr | fr/03.jpg | À vérifier | — |
| fr | fr/04.jpg | À vérifier | — |
| fr | fr/05.jpg | À vérifier | arome naturel |
| zh | zh/01.jpg | À vérifier | — |
| zh | zh/02.jpg | À vérifier | — |
| zh | zh/03.jpg | À vérifier | — |
| zh | zh/04.jpg | À vérifier | 乳清粉 |
| zh | zh/05.jpg | À vérifier | — |

## Per-image results — Fast mode off

| lang | image | status | CER (content) | CER (strict) | ing. recall | ing. precision | verdict expected | verdict actual | ok | flag recall | false alarms | blocks detected | blocks kept | strategy | retry | warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | ar/01.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 52 | 48 | three_pass | — | 59.30 |
| ar | ar/02.jpg | ok | 79.86% | 80.00% | 0.154 | 0.200 | À vérifier | À vérifier | yes | 0.000 | 1 | 45 | 41 | three_pass | — | 46.26 |
| ar | ar/03.jpg | ok | 53.51% | 59.48% | 0.200 | 0.400 | À vérifier | À vérifier | yes | 1.000 | 0 | 33 | 29 | three_pass | — | 31.86 |
| ar | ar/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 7 | 5 | three_pass | tiled:discarded:9.12s | 17.01 |
| ar | ar/05.jpg | ok | 74.36% | 72.90% | 0.400 | 0.500 | À vérifier | À vérifier | yes | 0.000 | 0 | 15 | 13 | three_pass | — | 16.62 |
| en | en/01.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 14 | 9 | three_pass | tiled:discarded:31.93s | 50.53 |
| en | en/02.jpg | ok | 64.00% | 65.00% | 0.200 | 0.500 | À vérifier | À vérifier | yes | 0.000 | 0 | 57 | 41 | three_pass | — | 59.15 |
| en | en/03.jpg | ok | 75.66% | 75.91% | 0.087 | 0.500 | À vérifier | À vérifier | yes | 0.000 | 0 | 4 | 3 | three_pass | — | 17.48 |
| en | en/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 6 | 2 | three_pass | — | 8.32 |
| en | en/05.jpg | ok | 48.59% | 51.76% | 0.524 | 0.846 | À vérifier | À vérifier | yes | 0.000 | 0 | 23 | 17 | three_pass | — | 27.88 |
| fr | fr/01.jpg | no ingredients section found | — | — | — | — | Incompatible ingredient detected | À vérifier | NO | — | — | 11 | 4 | three_pass | — | 25.30 |
| fr | fr/02.jpg | ok | 0.00% | 0.00% | 1.000 | 1.000 | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | yes | 1.000 | 0 | 1 | 1 | three_pass | — | 3.12 |
| fr | fr/03.jpg | ok | 62.96% | 64.65% | 0.000 | 0.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 28 | 26 | three_pass | — | 31.67 |
| fr | fr/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 9 | 6 | three_pass | — | 11.93 |
| fr | fr/05.jpg | ok | 28.12% | 25.98% | 0.600 | 0.750 | À vérifier | À vérifier | yes | 0.000 | 0 | 8 | 8 | three_pass | — | 16.01 |
| zh | zh/01.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 19 | 19 | three_pass | — | 27.35 |
| zh | zh/02.jpg | ok | 54.17% | 56.25% | 0.286 | 0.667 | À vérifier | À vérifier | yes | 1.000 | 0 | 3 | 2 | three_pass | — | 6.83 |
| zh | zh/03.jpg | ok | 23.81% | 26.92% | 1.000 | 0.833 | À vérifier | À vérifier | yes | 1.000 | 0 | 4 | 4 | three_pass | — | 7.29 |
| zh | zh/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 6 | 6 | three_pass | — | 13.58 |
| zh | zh/05.jpg | ok | 40.00% | 30.77% | 0.667 | 0.667 | À vérifier | À vérifier | yes | 1.000 | 0 | 4 | 4 | three_pass | — | 4.91 |

## Per-language summary — Fast mode off

| language | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | 5 | 3/5 | 69.24% | 74.36% | 0 | 0 | 0.251 | 0.367 | 5/5 | 0.333 | 1 | 34.21 |
| en | 5 | 3/5 | 62.75% | 64.00% | 0 | 0 | 0.270 | 0.615 | 5/5 | 0.000 | 0 | 32.67 |
| fr | 5 | 3/5 | 30.36% | 28.12% | 1 | 1 | 0.533 | 0.583 | 4/5 | 0.667 | 0 | 17.61 |
| zh | 5 | 3/5 | 39.33% | 40.00% | 0 | 0 | 0.651 | 0.722 | 5/5 | 1.000 | 0 | 11.99 |

### Overall — Fast mode off

| scope | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL | 20 | 12/20 | 50.42% | 53.84% | 1 | 1 | 0.427 | 0.572 | 19/20 | 0.500 | 1 | 24.12 |

## Per-image results — Fast mode on

| lang | image | status | CER (content) | CER (strict) | ing. recall | ing. precision | verdict expected | verdict actual | ok | flag recall | false alarms | blocks detected | blocks kept | strategy | retry | warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | ar/01.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 52 | 40 | language_first:ar | — | 23.69 |
| ar | ar/02.jpg | ok | 79.86% | 80.00% | 0.154 | 0.200 | À vérifier | À vérifier | yes | 0.000 | 1 | 45 | 41 | language_first:ar+fr | — | 25.91 |
| ar | ar/03.jpg | ok | 53.51% | 59.48% | 0.200 | 0.400 | À vérifier | À vérifier | yes | 1.000 | 0 | 33 | 29 | language_first:ar+fr | — | 18.47 |
| ar | ar/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 7 | 5 | language_first:all | tiled:discarded:9.16s | 17.16 |
| ar | ar/05.jpg | ok | 73.50% | 72.90% | 0.400 | 0.571 | À vérifier | À vérifier | yes | 0.000 | 0 | 15 | 12 | language_first:ar | — | 9.67 |
| en | en/01.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 14 | 9 | language_first:fr | tiled:discarded:7.6s | 19.09 |
| en | en/02.jpg | ok | 64.00% | 65.00% | 0.200 | 0.500 | À vérifier | À vérifier | yes | 0.000 | 0 | 57 | 40 | language_first:fr | — | 21.62 |
| en | en/03.jpg | ok | 75.66% | 75.91% | 0.087 | 0.500 | À vérifier | À vérifier | yes | 0.000 | 0 | 4 | 3 | language_first:all | — | 17.50 |
| en | en/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 6 | 2 | language_first:all | — | 8.85 |
| en | en/05.jpg | ok | 48.59% | 51.76% | 0.524 | 0.846 | À vérifier | À vérifier | yes | 0.000 | 0 | 23 | 17 | language_first:fr | — | 14.51 |
| fr | fr/01.jpg | no ingredients section found | — | — | — | — | Incompatible ingredient detected | À vérifier | NO | — | — | 11 | 4 | language_first:fr | — | 18.01 |
| fr | fr/02.jpg | ok | 0.00% | 0.00% | 1.000 | 1.000 | No incompatible ingredient found in the reference | No incompatible ingredient found in the reference | yes | 1.000 | 0 | 1 | 1 | language_first:all | — | 3.06 |
| fr | fr/03.jpg | ok | 62.96% | 64.65% | 0.000 | 0.000 | À vérifier | À vérifier | yes | 1.000 | 0 | 28 | 26 | language_first:fr | — | 13.18 |
| fr | fr/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 9 | 6 | language_first:fr | — | 10.24 |
| fr | fr/05.jpg | ok | 28.12% | 25.98% | 0.600 | 0.750 | À vérifier | À vérifier | yes | 0.000 | 0 | 8 | 8 | language_first:all | — | 16.16 |
| zh | zh/01.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 19 | 19 | language_first:fr+zh | — | 24.26 |
| zh | zh/02.jpg | ok | 54.17% | 56.25% | 0.286 | 0.667 | À vérifier | À vérifier | yes | 1.000 | 0 | 3 | 2 | language_first:all | — | 6.37 |
| zh | zh/03.jpg | ok | 23.81% | 26.92% | 1.000 | 0.833 | À vérifier | À vérifier | yes | 1.000 | 0 | 4 | 4 | language_first:all | — | 6.67 |
| zh | zh/04.jpg | no ingredients section found | — | — | — | — | À vérifier | À vérifier | yes | — | — | 6 | 6 | language_first:all | — | 13.03 |
| zh | zh/05.jpg | ok | 40.00% | 30.77% | 0.667 | 0.667 | À vérifier | À vérifier | yes | 1.000 | 0 | 4 | 4 | language_first:all | — | 4.73 |

## Per-language summary — Fast mode on

| language | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | 5 | 3/5 | 68.96% | 73.50% | 0 | 0 | 0.251 | 0.390 | 5/5 | 0.333 | 1 | 18.98 |
| en | 5 | 3/5 | 62.75% | 64.00% | 0 | 0 | 0.270 | 0.615 | 5/5 | 0.000 | 0 | 16.31 |
| fr | 5 | 3/5 | 30.36% | 28.12% | 1 | 1 | 0.533 | 0.583 | 4/5 | 0.667 | 0 | 12.13 |
| zh | 5 | 3/5 | 39.33% | 40.00% | 0 | 0 | 0.651 | 0.722 | 5/5 | 1.000 | 0 | 11.01 |

### Overall — Fast mode on

| scope | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL | 20 | 12/20 | 50.35% | 53.84% | 1 | 1 | 0.427 | 0.578 | 19/20 | 0.500 | 1 | 14.61 |

## Fast mode comparison (off vs on)

Mean warm time: 24.12s off, 14.61s on (1.65x).

| image | CER off | CER on | Δ CER | recall off | recall on | Δ recall | blocks 3-pass | blocks kept | strategy (on) | warm off s | warm on s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ar/01.jpg | — | — | — | — | — | — | 48 | 40 | language_first:ar | 59.30 | 23.69 |
| ar/02.jpg | 79.86% | 79.86% | +0.00 pp | 0.154 | 0.154 | +0.000 | 41 | 41 | language_first:ar+fr | 46.26 | 25.91 |
| ar/03.jpg | 53.51% | 53.51% | +0.00 pp | 0.200 | 0.200 | +0.000 | 29 | 29 | language_first:ar+fr | 31.86 | 18.47 |
| ar/04.jpg | — | — | — | — | — | — | 5 | 5 | language_first:all | 17.01 | 17.16 |
| ar/05.jpg | 74.36% | 73.50% | -0.86 pp | 0.400 | 0.400 | +0.000 | 13 | 12 | language_first:ar | 16.62 | 9.67 |
| en/01.jpg | — | — | — | — | — | — | 9 | 9 | language_first:fr | 50.53 | 19.09 |
| en/02.jpg | 64.00% | 64.00% | +0.00 pp | 0.200 | 0.200 | +0.000 | 41 | 40 | language_first:fr | 59.15 | 21.62 |
| en/03.jpg | 75.66% | 75.66% | +0.00 pp | 0.087 | 0.087 | +0.000 | 3 | 3 | language_first:all | 17.48 | 17.50 |
| en/04.jpg | — | — | — | — | — | — | 2 | 2 | language_first:all | 8.32 | 8.85 |
| en/05.jpg | 48.59% | 48.59% | +0.00 pp | 0.524 | 0.524 | +0.000 | 17 | 17 | language_first:fr | 27.88 | 14.51 |
| fr/01.jpg | — | — | — | — | — | — | 4 | 4 | language_first:fr | 25.30 | 18.01 |
| fr/02.jpg | 0.00% | 0.00% | +0.00 pp | 1.000 | 1.000 | +0.000 | 1 | 1 | language_first:all | 3.12 | 3.06 |
| fr/03.jpg | 62.96% | 62.96% | +0.00 pp | 0.000 | 0.000 | +0.000 | 26 | 26 | language_first:fr | 31.67 | 13.18 |
| fr/04.jpg | — | — | — | — | — | — | 6 | 6 | language_first:fr | 11.93 | 10.24 |
| fr/05.jpg | 28.12% | 28.12% | +0.00 pp | 0.600 | 0.600 | +0.000 | 8 | 8 | language_first:all | 16.01 | 16.16 |
| zh/01.jpg | — | — | — | — | — | — | 19 | 19 | language_first:fr+zh | 27.35 | 24.26 |
| zh/02.jpg | 54.17% | 54.17% | +0.00 pp | 0.286 | 0.286 | +0.000 | 2 | 2 | language_first:all | 6.83 | 6.37 |
| zh/03.jpg | 23.81% | 23.81% | +0.00 pp | 1.000 | 1.000 | +0.000 | 4 | 4 | language_first:all | 7.29 | 6.67 |
| zh/04.jpg | — | — | — | — | — | — | 6 | 6 | language_first:all | 13.58 | 13.03 |
| zh/05.jpg | 40.00% | 40.00% | +0.00 pp | 0.667 | 0.667 | +0.000 | 4 | 4 | language_first:all | 4.91 | 4.73 |

## Observations / suspected bugs

Listed, not fixed (evaluation is read-only).

- [fast off] ar/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] ar/01.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] ar/02.jpg: expected flags not raised: ['غليسرول']
- [fast off] ar/02.jpg: false-alarm flags: ['arômes', 'flavourings', 'الصويا بدون نكهات إصطناعية أ أو ICIAIS', 'نكهات', '香料']
- [fast off] ar/02.jpg: content CER 79.86% above the 3% target
- [fast off] ar/02.jpg: unrecognized ingredients: ['DESTA BOLACHA لا تحتوي', 'SIST مكونات هذا البسكويت على أي مادة تس', 'مواد رافعة الجلوتين', 'مواد معاملة الدقيق اليسيثين الصويا']
- [fast off] ar/02.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] ar/02.jpg: 3 products detected; verdict aggregated by severity (worst case)
- [fast off] ar/03.jpg: content CER 53.51% above the 3% target
- [fast off] ar/03.jpg: unrecognized ingredients: ['املاح مستحلبة حافظة سوربات']
- [fast off] ar/03.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] ar/03.jpg: 2 products detected; verdict aggregated by severity (worst case)
- [fast off] ar/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] ar/04.jpg: 3 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] ar/04.jpg: no heading on the first pass; tiled retry discarded (9.12s, blocks 5 -> 6)
- [fast off] ar/05.jpg: expected flags not raised: ['نكهة']
- [fast off] ar/05.jpg: content CER 74.36% above the 3% target
- [fast off] ar/05.jpg: unrecognized ingredients: ['توم', 'صلصة مطهوة ومركزا الطماطم ive', 'لح', 'نكة البصل الطبيعية بص']
- [fast off] ar/05.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] en/01.jpg: 12 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/01.jpg: no heading on the first pass; tiled retry discarded (31.93s, blocks 9 -> 16)
- [fast off] en/02.jpg: expected flags not raised: ['lecithins']
- [fast off] en/02.jpg: content CER 64.00% above the 3% target
- [fast off] en/02.jpg: 16 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/03.jpg: expected flags not raised: ['whey powder', 'flavouring']
- [fast off] en/03.jpg: content CER 75.66% above the 3% target
- [fast off] en/03.jpg: unrecognized ingredients: ['graa padano miecroacesemi other']
- [fast off] en/03.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] en/04.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] en/05.jpg: expected flags not raised: ['flavouring']
- [fast off] en/05.jpg: content CER 48.59% above the 3% target
- [fast off] en/05.jpg: unrecognized ingredients: ['e r']
- [fast off] en/05.jpg: 8 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] fr/01.jpg: verdict mismatch — expected 'Incompatible ingredient detected', got 'À vérifier'
- [fast off] fr/01.jpg: 7 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/03.jpg: content CER 62.96% above the 3% target
- [fast off] fr/03.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] fr/04.jpg: 5 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] fr/05.jpg: expected flags not raised: ['arome naturel']
- [fast off] fr/05.jpg: content CER 28.12% above the 3% target
- [fast off] fr/05.jpg: unrecognized ingredients: ['ognons', 'su']
- [fast off] zh/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] zh/02.jpg: content CER 54.17% above the 3% target
- [fast off] zh/02.jpg: unrecognized ingredients: ['草菇', '非转基因']
- [fast off] zh/02.jpg: 1 block(s) unreadable or uncertain (dropped but recorded)
- [fast off] zh/03.jpg: content CER 23.81% above the 3% target
- [fast off] zh/03.jpg: unrecognized ingredients: ['三聚', '方法', '鸡胸肉', '黑椒']
- [fast off] zh/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast off] zh/05.jpg: content CER 40.00% above the 3% target
- [fast off] zh/05.jpg: unrecognized ingredients: ['含tbhq', '花椒年化似油']
- [fast on] ar/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] ar/01.jpg: 12 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] ar/02.jpg: expected flags not raised: ['غليسرول']
- [fast on] ar/02.jpg: false-alarm flags: ['arômes', 'flavourings', 'الصويا بدون نكهات إصطناعية أ أو ICIAIS', 'نكهات', '香料']
- [fast on] ar/02.jpg: content CER 79.86% above the 3% target
- [fast on] ar/02.jpg: unrecognized ingredients: ['DESTA BOLACHA لا تحتوي', 'SIST مكونات هذا البسكويت على أي مادة تس', 'مواد رافعة الجلوتين', 'مواد معاملة الدقيق اليسيثين الصويا']
- [fast on] ar/02.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] ar/02.jpg: 3 products detected; verdict aggregated by severity (worst case)
- [fast on] ar/03.jpg: content CER 53.51% above the 3% target
- [fast on] ar/03.jpg: unrecognized ingredients: ['املاح مستحلبة حافظة سوربات']
- [fast on] ar/03.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] ar/03.jpg: 2 products detected; verdict aggregated by severity (worst case)
- [fast on] ar/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] ar/04.jpg: 3 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] ar/04.jpg: no heading on the first pass; tiled retry discarded (9.16s, blocks 5 -> 6)
- [fast on] ar/05.jpg: expected flags not raised: ['نكهة']
- [fast on] ar/05.jpg: content CER 73.50% above the 3% target
- [fast on] ar/05.jpg: unrecognized ingredients: ['توم', 'صلصة مطهوة ومركزا الطماطم لتحضي الم دوار الشمس', 'لح', 'نكة البصل الطبيعية بص']
- [fast on] ar/05.jpg: 3 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] en/01.jpg: 12 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/01.jpg: no heading on the first pass; tiled retry discarded (7.6s, blocks 9 -> 16)
- [fast on] en/02.jpg: expected flags not raised: ['lecithins']
- [fast on] en/02.jpg: content CER 64.00% above the 3% target
- [fast on] en/02.jpg: 17 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/03.jpg: expected flags not raised: ['whey powder', 'flavouring']
- [fast on] en/03.jpg: content CER 75.66% above the 3% target
- [fast on] en/03.jpg: unrecognized ingredients: ['graa padano miecroacesemi other']
- [fast on] en/03.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] en/04.jpg: 4 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] en/05.jpg: expected flags not raised: ['flavouring']
- [fast on] en/05.jpg: content CER 48.59% above the 3% target
- [fast on] en/05.jpg: unrecognized ingredients: ['e r']
- [fast on] en/05.jpg: 8 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] fr/01.jpg: verdict mismatch — expected 'Incompatible ingredient detected', got 'À vérifier'
- [fast on] fr/01.jpg: 7 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/03.jpg: content CER 62.96% above the 3% target
- [fast on] fr/03.jpg: 2 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] fr/04.jpg: 5 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] fr/05.jpg: expected flags not raised: ['arome naturel']
- [fast on] fr/05.jpg: content CER 28.12% above the 3% target
- [fast on] fr/05.jpg: unrecognized ingredients: ['ognons', 'su']
- [fast on] zh/01.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] zh/02.jpg: content CER 54.17% above the 3% target
- [fast on] zh/02.jpg: unrecognized ingredients: ['草菇', '非转基因']
- [fast on] zh/02.jpg: 1 block(s) unreadable or uncertain (dropped but recorded)
- [fast on] zh/03.jpg: content CER 23.81% above the 3% target
- [fast on] zh/03.jpg: unrecognized ingredients: ['三聚', '方法', '鸡胸肉', '黑椒']
- [fast on] zh/04.jpg: no ingredients section found (reported as a status; CER and recall are n/a, not 100%)
- [fast on] zh/05.jpg: content CER 40.00% above the 3% target
- [fast on] zh/05.jpg: unrecognized ingredients: ['含tbhq', '花椒年化似油']

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
