# The appearance update

One vocabulary for how oMLX looks, so the app and the console cannot drift apart:
a single token file is the source for the type scale, the colours and the
spacing; the console gets a shared layer (one number formatter, one set of
interaction pieces, one component spec) and its screens are rebuilt on it; the
app stops typing its own point sizes and names the same six steps; and the
wording that had drifted between the two surfaces is aligned.

Nothing here touches model loading, scheduling, engines or the API protocols.

## What each open PR carries

| PR | In the series | What it does | Stands on |
|---|---|---|---|
| #4082 | yes — the foundation | the app's token source: `tokens.json`, the generator, the generated `DesignTokens.swift`, and the drift guard | `main` |
| #3847 | yes — the visible half | every `.omlxText` / `.omlxMono` / `.omlxDisplay` call names one of the six steps instead of a number | #4082 |
| #3848 | yes | the ten console catalogues: a capital T on the token words, the layout block translated, the values still in English filled in | `main` |
| #3849 | yes — console foundation | the console's own token pipeline (colours, space, radius, layout, `tokens.css`) plus the shared layer | #3848, #4082 |
| #3850 | yes | the eight console screens rebuilt on that layer, and the 10.9 MB font payload removed | #3849 |
| #3851 | yes | the chat page's right panel becomes the console's shared drawer | #3850 |
| #4005 | yes | every console visual value resolves through a token instead of a Tailwind default | #3851 |
| #3824 | yes | a capital T on the token words and on the `PP` / `TG` labels in the app | `main` |
| #3863 | yes | a hint under a control in the model sheet spans the card instead of wrapping inside the label column | `main` |
| #3826 | yes — parked draft | count in 万 / 亿 in Chinese; kept aside until that ladder is wanted | `main` |
| #3773 | no | one envelope builder for both response paths | `main` |
| #3810 | no | the app's Logs screen reads as records: columns, one colour per level, repeats collapsed | `main` |
| #3875 | no | downloads gain a live transfer speed, queues that survive a restart, and an immediate xet cancel | `main` |
| #3914 | no | the app drops the Claude Code context-scaling controls the server no longer has | `main` |
| #3915 | no | the menubar refresh interval actually defaults to 0.5 s, pinned where CI can see it | `main` |
| #3950 | no | DeepSeek Harness becomes a launch target: a console row, an app row, the translated READMEs | `main` |

## Order

```
#4082 ──┬──► #3847                                     (the app's type scale)
        └──► #3848 ──► #3849 ──► #3850 ──► #3851 ──► #4005   (the console)

#3824 #3863 · #3773 #3810 #3875 #3914 #3915 #3950 : on `main` alone
```

Only the console column has an order, and it needs #3848 because its own tests
pin the catalogue those ten files fix. Everything else is conflict-free against
`main` on its own — the rows marked **no** are not part of this series at all.
