# The tabletop experiment

Before Operation Antitelephone opened, its keeper ran a small, pre-registered experiment on an ordinary desktop PC. The question:
**can one program send information to another program forward in time, backward in time, or both, through a real physical
channel?**

## Method

- **The channel.** Two separate processes share no files, pipes, sockets or memory. The only link between them is physical: a
  *transmitter* keeps a CPU core busy to send a 1 and idles to send a 0, and a *receiver* counts how much work it gets done in
  each time slot. CPU contention carries the bits.
- **Forward test.** The receiver's reading in slot *i* is compared with the bit sent in slot *i*.
- **Backward test.** The receiver's reading in slot *i* is compared with the bit created **later**, at the start of slot *i + 1*,
  by the operating system's cryptographic random generator. Each reading is fixed before the next bit exists.
- **Pre-registration.** The program, number of runs, statistics and success threshold were fixed and hashed before the first
  run. A backward signal would count only if it reached p < 10⁻⁶ in one run **and** repeated in a second run.
- **Two arms.** The original program's CPU pinning silently failed on 64-bit Windows, so the processes did not share a core.
  This was caught in a pre-flight review. The fix was registered before any run, and both versions were run: arm U unmodified,
  arm P with pinning fixed.

## Results

| Run | Arm | Test | Forward | Backward (pairs matched) | Verdict |
|---|---|---|---|---|---|
| R1 | U | message | `IT WORKS` → `I\????KK` (17/64 bits wrong) | – | – |
| R2 | U | random bits | 92.5% (p ≈ 10⁻²⁰) | 52.1% (p = 0.71) | no backward signal |
| R3 | U | random bits | 50.0% (channel failed) | 51.6% | not tested |
| R4 | P | message | `IT WORKS` → `IT WORKS` (0/64 wrong) | – | – |
| R5 | P | random bits | 100.0% (1000/1000) | 51.5% (p = 0.38) | no backward signal |
| R6 | P | random bits | 99.9% (999/1000) | 49.2% (p = 0.66) | no backward signal |

Combined, arm P matched 1,006 of 1,998 backward pairs: 50.35%, a 95% confidence interval of 48.2–52.5%. An additional
count-level analysis (exploratory, not pre-registered) limits any backward influence to under about 1% of the forward
signal's strength.

Two independent from-scratch recomputations agreed with every reported number, and two adversarial reviews found the
conclusion sound.

## Conclusion

Information went forward through the channel almost perfectly, and nothing came back from the future. This is exactly what
physics predicts.

## Caveats, stated honestly

- With near-perfect decoding, the registered backward accuracy test mostly checks the random generator's serial independence.
  The registered count-level test could only detect a backward effect of about 15% of the forward signal or more. The tighter
  ~1% bound comes from an exploratory analysis.
- When pinned to one core, the receiver was sometimes held off the CPU past its time window. Its count was always fixed in time,
  but some of its log entries were written after the next bit existed. Those timestamps carry an ordinary, forward-in-time
  artefact that can look like a backward signal, so only the counts are evidence.
- The comparison between the two arms is confounded by run order and slot length.

The raw logs, the pre-registration and the hash manifest are kept by the keeper and can be published on request.
