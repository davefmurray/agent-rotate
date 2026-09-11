# Fable 5.1 rendered-asset reviews

## Final public-repository cut

2026-09-11. Model `claude-fable-5-1`, restricted to Read, reviewed the final end card, contact sheet, and revised posts. This supersedes the first cut's private-repository CTA. Fable's response:

**APPROVE**

Verified against the stills only:

- **URL**: end card and both posts use the public path github.com/davefmurray/agent-rotate. No "private", "invite", or waitlist wording anywhere.
- **CTA**: "GET STARTED ON GITHUB" label present above the URL box on the end card and slide 06 of the contact sheet.
- **Clipping**: none visible. All headlines, boxes, footer, and progress bars sit inside the frame on every slide.
- **Feature claims**: same-provider retry before response delivery, session stays open, no partial replay, wrapper-launched scope, and the four control features all match the product description.
- **Labels**: ILLUSTRATION on slides 01 to 03, SAMPLE DATA on slide 04 and its dashboard title, sample-data plus injected-429 disclaimer on the end card.
- **Post lengths**: I recounted both. Primary is 272 weighted, alternate 275, URL weighted at 23. Matches your corrected figures.

Frame timestamps on the sheet fall within the stated 22-25s end-card hold. No playback checked.

## First cut (before public-repository correction)


2026-09-11. Explicit native model: `claude-fable-5-1`. Read-only inspection of the six-scene contact sheet, full-size scenes 3 and 4, and both X post drafts. This is Fable's verbatim response to the first rendered cut.

**Verdict: APPROVE** (visual inspection only; motion items listed separately as unverified).

**What checks out in the stills**

- Text clipping: none. All copy sits inside the 5% safe margin in scene-3.png and scene-4.png and across all six contact-sheet frames. The scene 3 account boxes end at roughly the 95% line, which is at the edge but not over it.
- Hierarchy: headline, subhead, chip, footer order is consistent on every frame. Feature labels dominate scene 4 and the table reads as supporting detail, as intended.
- X feed legibility: headlines and chips are large enough. The scene 3 scope footer measures around 39px Arial, above the 36px floor. Scene 4 table text is around 26px, which is under the floor but was explicitly accepted as supporting image detail.
- Factual claims: every on-screen statement matches the fact sheet. Scope sentence in scene 3 is verbatim. Version, "private repo", "your own accounts", "same provider", "no partial replay", "native approvals and sandbox unchanged", and "routing applies to wrapper-launched sessions" are all present and accurate. No forbidden phrases (available now, download, open source, unlimited, bypass, savings, API/model fallback, testimonials). The dashboard shows sample rows only, no real names, emails, or tokens, and carries SAMPLE DATA both as a chip and in the mock title bar.
- CTA: "Want access?" plus a lime "Reply ROTATE for details." pill, matching the post drafts. The 24.5s frame works as a thumbnail.
- Posts: both drafts are accurate and within the character limit. "Same approvals" in the alternate is supported by the native-approvals-preserved fact. No changes needed.

**Non-blocking notes, fix only if cheap**

- Scene 4 chips do not sit under their target columns. QUOTA WINDOWS sits under Provider, RESET TIMERS under Quota window, CREDENTIAL HEALTH under Resets. If the motion draws callout lines to the right columns this is moot. If not, slide the chips under Quota window, Resets, and State respectively.
- Scene 2 has a small three-node switching glyph on the right with no ILLUSTRATION chip. It is abstract enough to pass, but the storyboard rule says switching diagrams carry the chip. Either add the chip or drop the glyph.
- Scene 6 has no bottom-right wordmark and adds an extra line, "Claude Code + Codex. One local router." Both are acceptable.

**Cannot verify from stills (motion)**

- Frame 0 shows terminal text rather than black, and the 429 line lands at 0.6s.
- Request pill travels to Account A, returns on 429, and lands on Account B, with the session node never changing state.
- ILLUSTRATION chip persists for all of scene 3 and SAMPLE DATA for all of scene 4.
- Static hold from 24.0s to 25.0s, exact 25.0s duration, 1920x1080 at 30fps, silent H.264.
- Poster frames at 1.0s and 24.5s exported.

Codex should confirm those five points with timestamps or a frame dump before the post goes out.

## Production follow-up

Codex applied the two inexpensive suggestions: the dashboard feature labels now connect to their corresponding State, Quota window, and Resets columns; the intro route graphic now carries ILLUSTRATION. The moving request follows the complete connector path to each account. The end card holds completely still for three seconds, and the opening poster is exported at 1.0s. The final encoding and decoded frames are checked separately in `validation.json`.
