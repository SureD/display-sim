# M3 temporal parameters and validation

2026-10-16. All tunable ranges are **unmeasured priors**. Equations are proposed
simulator models, not vendor algorithms. See [M1 temporal](04-temporal.md).

## Response and state

Use `q_next=u+(q_prev-u)*exp(-dt/tau)` with dt and tau in ms.
`response_time_ms` currently means **tau**, not quoted gray-to-gray t10–90.
`t10–90=ln(9)*tau`; settling within 1% takes `ln(100)*tau`.
Split rise/fall or use a start/target-gray LUT when measurements exist.

| Transition | t10–90 prior (ms) | Corresponding tau (ms) |
|---|---:|---:|
| LCD main | 2–20 | 0.91–9.10 |
| Slow VA dark | 20–50 | 9.10–22.76 |
| OLED main | 0.05–1 | 0.023–0.455 |

Current synthetic tau values: VA 8→t10–90 17.58 ms; IPS 12→26.37 ms;
WOLED .2→.439 ms; QD-OLED .1→.220 ms. The IPS fixture is a slower-than-main
example; do not silently reinterpret its 12 as t10–90. Main-transition ranges
do not bound near-black behavior. [RTINGS methodology](https://www.rtings.com/tv/tests/motion/motion-blur-and-response-time)
is a primary measurement reference; definitions and test versions must match.

Response should ultimately run on LCD transmission/emitter state, before optics
and eye integration. Skeleton filters emitted RGB instead; independently changing
backlight and response will need a drive-state interface. First frame is settled;
pre-roll black for black→white tests, preserve state for repeated calls, and
reset between independent clips. Save **unblurred** state. For a fixed target
and no overdrive, output stays between old and new levels, rises/falls monotonically,
and converges; a longer dt advances further. Test both onset and afterglow.

## Overdrive (new fields required)

Proposed command: `u_OD=clip(u+k*(u-q_start),u_min,u_max)` for t_OD,
then u for the remaining interval. Integrate both segments using the same
exponential update; do not hold the boosted command indefinitely. Suggested
k=0–1, t_OD=.5–8 ms, start disabled k=0. Gains/headroom are uncertain and
transition-specific. Normalized optical clamp [0,1] cannot represent every
voltage-driven overshoot near the rails; fit an electrical LUT or explicitly
label an effective optical surrogate. Record overshoot as
`max(0,(max(q)-u)/(u-q_start))` for a rising transition and undershoot analogously.
Test k=0 identity to the base model, bounded drive, transient overshoot on an
intermediate-gray transition when headroom allows, and eventual settling.
No overdrive parameter exists in the current schema; these are implementer tests,
not skipped tests or claimed coverage in this support commit.

## BFI, hold and smear

BFI is an emission gate after response: m(y,t) in {0,1}, with optional row phase.
`T_visible=d/f`; fixed peak drive gives mean luminance d times full hold.
Default d=1; explore .1–1, with .25/.5/.75 useful synthetic settings. Do not
multiply peak by 1/d without a separate current/power budget. New duty/phase
fields and subframe emission samples are required; `sample_and_hold=false`
currently only bypasses pursuit blur and does **not** implement BFI.

At v=960 pixels/s (blur support, not 10–90 edge width):

| Refresh | Duty | Visible duration ms | Hold smear pixels |
|---:|---:|---:|---:|
| 60 | 1 | 16.667 | 16 |
| 120 | 1 | 8.333 | 8 |
| 60 | .5 | 8.333 | 8 |
| 120 | .25 | 2.083 | 2 |

Set `motion_px_per_frame=v*frame_time_ms/1000`; positive/negative values
reverse horizontal tracking. Sweep 0,2,4,8,16 pixels/frame. Current renderer
averages seven bilinear shifts uniformly from -motion/2 to +motion/2, edge-clamped;
this is a symmetric one-axis pursuit proxy. A response trail is directional and
has characteristic length `abs(v)*tau_seconds` (VA tau=8 ms →7.68 pixels
at 960 px/s); do not conflate it with rectangular hold support or add widths
as an exact combined blur metric. Keep response tau zero/history absent when
isolating hold blur. Check zero-motion/bypass identity, DC preservation,
more edge spreading with larger motion, and no accumulation of eye blur in state.

For a physical renderer integrate emitted L(x+v_eye*t,t) over exposure, with row
scanout offset `y*Tscan/H`. Use temporal sampling <=min(tau,T_visible)/10 and
halve steps until mean/edge metrics change <1%; analytic response updates avoid
stiff OLED stepping. Frame repeats do not create new motion positions. BFI duty
alone does not specify pulse count, phase or crosstalk; PWM is separate (provisional
120–2000 Hz sweep). Open: LUT/temperature/VRR data, scanout, true BFI waveform,
overdrive headroom and pursuit exposure convention. Current added tests cover
history/trailing/convergence and hold-state isolation, not those new features.
