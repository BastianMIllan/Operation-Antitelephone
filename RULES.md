# Operation Antitelephone: rules (version 1, fixed)

These rules never change. This file's SHA-256 is stated in the station's README and in the commit that added it, and the
repository's history shows any change. Forks keep copies of this file.

## The idea

A message from the future can only arrive if a receiver is already switched on and waiting. The **station** is the
GitHub repository `BastianMIllan/Operation-Antitelephone` (https://github.com/BastianMIllan/Operation-Antitelephone), and the same repository
if it is ever renamed or moved as a whole. Forks and copies are not the station. It is open to anyone, at any time, with
no end date.

## What to send

1. **Pick a target minute T.** Any whole minute in UTC that is at least 60 minutes after the moment you send.
2. **Find the code for T.** It is the `outputValue` of the NIST Randomness Beacon version 2.0 pulse whose `timeStamp` is
   exactly T, as returned by `https://beacon.nist.gov/beacon/2.0/pulse/time/<T in milliseconds since 1970-01-01 00:00 UTC>`.
   For T = 2026-12-01 00:00 UTC that is `https://beacon.nist.gov/beacon/2.0/pulse/time/1796083200000`.
   Use `outputValue` only, not `localRandomValue`, `signatureValue` or any other field.
   Write **at least its first 16 characters** (the leftmost ones), together, in upper or lower case. Writing more is
   allowed, but every character must match.
3. **Open a new issue in the station** whose description contains a TARGET line, for example:

   `TARGET 2026-12-01 00:00 UTC = 0123456789abcdef`

   You can type it yourself on GitHub, or run `send.py` from the station's repository, which fills it in for you.
4. **Recommended:** before T, check that your issue is visible when you are logged out of GitHub, and save its page in a
   public web archive (for example https://web.archive.org/save). This gives independent proof that it existed before T.

## How a message is read

- **A message is one issue** (not a pull request) opened directly in the station. Only its description counts, as
  GitHub stores it (the `body` field in GitHub's API), not as a web page displays it. The title, comments, labels,
  images and link previews are ignored.
- Characters in Unicode general category Cf (invisible formatting characters, such as zero-width spaces) are ignored.
  Tabs and characters in Unicode general category Zs (every kind of space) count as spaces. Digits mean 0-9, and a
  letter means any character in Unicode general category L. Categories are as defined in Unicode 15.0.
- **A TARGET line** is the word TARGET, in any letter case and not directly after another letter, followed on the same
  line by a date written YYYY-MM-DD, with nothing in between except spaces and at most one colon.
- **One attempt per message:** a message that contains more than one TARGET line is **invalid**. Apart from its TARGET
  line, everything in the message is ignored.
- **Reading the TARGET line.** After the date, the line must continue in exactly this order, on the same line. Spaces
  are allowed between the parts.
  1. a space or the letter T (or t);
  2. the time as H:MM or HH:MM, from 0:00 to 23:59;
  3. optionally `:00`, which may be followed by a dot and zeros (all the zeros written there);
  4. optionally the letters `UTC`, `GMT` or `Z`, in any letter case;
  5. optionally `=`;
  6. optionally `0x` (or `0X`). If those two characters stand here, they are always this part, never the start of the code;
  7. the code: the unbroken run of characters 0-9, a-f, A-F that starts there. It ends at the first character of any
     other kind. Anything after the code is ignored.

  The time is always read as UTC, and nothing else in the message changes that. A line that does not fit this pattern,
  or whose date does not exist, is **unreadable**.

## When it counts as a hit

- **Opened here:** the issue was opened directly in the station. An issue moved in from another repository (GitHub shows
  "transferred this issue from ...") or created with an import tool that lets a repository admin choose its creation time
  does not count.
- **On time:** the issue was created at least 60 minutes before T, according to the creation time GitHub's servers record
  for it: the `created_at` (or `createdAt`) value in GitHub's API, in UTC, to the second. The issue page shows that time
  only to the minute and in the viewer's time zone, so use the API value.
- **Never edited:** a message whose description was ever edited after it was created, by anyone (GitHub marks it
  "edited"), is **invalid**. Changes to the title do not matter. To change a message, open a new issue.
- **Correct:** the code has at least 16 characters, and every one equals the start of the beacon's `outputValue` for T
  (upper and lower case count as the same).

**Results.** A message that is invalid or unreadable, or is not opened here, not on time or edited, or whose code has
fewer than 16 characters, is a **miss**, whatever NIST publishes. For any other message: if NIST has not yet published
a pulse at or after T, it is **pending**; if NIST has published later pulses but none whose timeStamp is exactly T (an
outage), or the address above has served no new pulse for a whole year and T is after its last pulse, it is **void**;
if the code is correct, it is a **hit**; otherwise it is a **miss**. The robot also names the reason for a miss, such as
too late, invalid or unreadable.

## Why one hit would be proof

Nobody outside NIST can know the code for T before NIST publishes it, about a minute after T. NIST itself fixes the random
part about one minute before T and commits to it in the previous pulse. The values come from hardware random-number
generators and are signed by NIST. Guessing 16 hexadecimal characters succeeds 1 time in 2^64 (about 18 quintillion).
Even a billion spam guesses would have about 1 chance in 18 billion of a single lucky hit.

## The robot

A program in the station (`station.py`, run by GitHub Actions) reads each message, replies with what it read, and later
replies with the result. It is a helper: these rules decide, and anyone can check a result by hand. The robot can be
delayed, so the time of its reply never decides a result by itself.

## How anyone can check a claimed hit

1. Read the issue's `created_at` and `body` from GitHub's API (`https://api.github.com/repos/<owner>/<repo>/issues/<number>`).
   Check that the description is not marked "edited" and that the issue was not transferred in.
2. Open the beacon address above for T. Confirm that `timeStamp` equals T exactly, then compare with `outputValue`.
3. Look for records made before T that the keeper cannot alter: the time of the robot's first reply on the issue; the
   issue's `opened` event in the public GitHub event archive (https://www.gharchive.org), whose time must match the
   issue's creation time; and any web-archive copy saved before T. The issue's number should also be in time order
   with its neighbours. A hit that no such record supports rests only on trust in the keeper.
4. Or run `python station.py verify <issue number>` from the station's repository.

## Promises from the station keeper

- Messages are never edited, deleted, hidden, transferred or converted to discussions by the keeper. The keeper never
  moves issues into the station and never creates issues with a chosen creation time. The label "not a message" is used
  only on the keeper's own notices. The repository stays public, its issues stay switched on, and finished messages stay
  visible (closed issues remain public).
- This file is never changed and the repository's history is never rewritten. A future version, if ever needed, would be
  a new station with a new name.
- If the keeper ever learns a way to send information back in time, it will be used to send beacon codes to this station.

## Limits, stated honestly

- This trusts NIST, which alone produces the values, not to know or reveal them more than about a minute ahead.
- This trusts GitHub's recorded creation times and edit markers. A repository admin can bring in issues with an earlier
  creation time (by transfer or import), so a hit is convincing only with the records listed in "How anyone can check".
- This trusts the keeper to keep the promises above. Public archives make breaking them visible.
- Known physics predicts silence. The station costs nothing to keep open, and a single verified hit could not be argued with.

Listening since this file was first published.
