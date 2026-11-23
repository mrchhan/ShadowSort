# Changelog

## 1.6.1
- **Big events:** 16,000+ photos and thousands of people now work. Grouping faces is hundreds of times faster (one matrix product per face instead of comparing every group with every other).
- People are shown 60 at a time with **Show more** and a **Find a person** box; the "Same person as…" list fills only when opened.
- Face thumbnails are prepared in parallel with fast JPEG decoding.
- New setting: only list people who appear in at least N photos (hides one-off guests).
- New progress steps: *grouping faces* and *preparing people*.
- The filing animation moves a sample of 2,500 photos, so it stays smooth with huge folders.

## 1.6.0
- Each person's folder is split into **Solo / Small Group / Group**. Background faces don't count, and veiled, side-on or distant faces still count as "someone else is in the photo".
- New **Group Photos** folder with every big group photo once.
- **Together:** photos that contain all of the people you pick, as a folder or a ZIP.
- **Export** lets you pick which kinds go into each person's ZIP, with optional sub-folders.
- People cards show *solo · small · group* counts, and **Photos / fix** can filter by kind.
- Settings: where a big group starts, plus on/off switches for the split and the Group Photos folder.

## 1.5.0 — first public release
- Sorts photos into folders by content (optional offline AI) and/or year and month.
- Finds exact and near-identical duplicates and keeps the best copy.
- Moves blurry, blank and broken photos to `_To Delete`. Nothing is ever deleted by the app.
- Face recognition: a folder per person using hard links (no extra space), names remembered between runs, *Same person?* suggestions, drag-to-merge, **Photos / fix** and a ZIP export per person.
- 9 animation styles: Mosaic, Globe, Galaxy, 3D Wall, Neural, Swipe Deck, Polaroid Desk, Matrix Rain and Black Hole.
- Preview before anything moves, Undo, Copy mode and a CSV report.
- Windows installer and portable zip, built automatically by GitHub Actions.
