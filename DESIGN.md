# Battle It Out visual direction

Initial implementation direction for CN-028, 2026-11-26. This is an engineering
choice for review, not approved event branding or evidence of a launched event.

The public page uses a dark navy strategy arena, condensed bold headings,
lime/coral team colors, lavender accents and a quiet monospace supporting voice.
The arena illustration is explicitly labeled. The page progresses from the
competition idea to the upload/trial/round flow, practical rules and account
access. No event dates, sponsors, testimonials or participation metrics are
invented. Battlecode attribution does not imply endorsement.

The private console uses the same color system in a light workspace and dark
navigation rail. Match room, analytics, submissions, disputes and Admin
operations are separate tasks. The dashboard brings deadline and tournament
notices together. The inbox uses text and color to distinguish read state and
places email controls in a separate panel. Navigation and forms remain usable on mobile;
wide data tables scroll within their panels rather than overflowing the page.
Canvas boards have a descriptive accessible label and score counters remain
available as text. Full nonvisual play-by-play is still accessibility work.

Typography uses DM Sans, Barlow Condensed and IBM Plex Mono from Google Fonts,
with local system fallbacks. Controls have labels, visible focus states and
keyboard access; errors/statuses use live regions. Source/protocol details do
not appear in public workflows except upload constraints that affect participant
choices. The initial UI is browser-tested, not a formal accessibility audit.

The console and public page let keyboard users skip directly to main content.
Direct links to restricted screens explain the required access and offer a
dashboard link. API error messages can include the server request ID for support.
