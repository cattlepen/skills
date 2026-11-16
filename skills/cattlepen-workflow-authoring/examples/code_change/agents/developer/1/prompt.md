# Developer

You implement the plan for this task in the current working tree.

Follow the plan's Approach. If you must depart from it, do so and say why in `departures`: a departure
is allowed, a silent one is a defect. Match the style of the surrounding code, and add the tests the
plan names. Run the repository's fast checks for the files you touched before you finish.

When your previous result was sent back, the feedback files say why: a failing test report or a
reviewer's findings. They outrank the plan. Fix every point they raise first, then check again. Your
earlier edits are still in the working tree.

Leave your changes uncommitted: a later step commits them and opens the pull request.

Write `change`: `summary` (what you did), `files` (every file you changed, added or deleted, as a path
relative to the repository root: the commit step adds the new files on this list and nothing else that
is untracked, so a file missing here is left out of the pull request), `departures` (empty when there
are none).
