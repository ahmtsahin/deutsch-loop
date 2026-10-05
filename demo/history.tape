# Renders the detailed terminal story with VHS: https://github.com/charmbracelet/vhs
# Run from the repository root:   vhs demo/history.tape
# Needs python and bash; macOS, Linux, and WSL work out of the box.
# Every screen is real engine output for a four-month learner story (scripts/demo.py).

Output demo/history-terminal.gif

Require python

Set Shell "bash"
Set FontSize 16
Set Width 1180
Set Height 760
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

Hide
Type "rm -rf demo-home && python scripts/demo.py --home demo-home --quiet > /dev/null"
Enter
Type `dna() { python scripts/deutsch_loop.py --home demo-home "$@"; }`
Enter
Type "clear"
Enter
Show

# 1. The tutor remembers you.
Type "dna recap --format card"
Sleep 400ms
Enter
Sleep 5s

# 2. Your FehlerDNA, and the root cause behind the symptoms.
Type "clear"
Enter
Type "dna summary --format text"
Sleep 400ms
Enter
Sleep 8s

# 3. One mistake, from first slip to mastered, with a new sentence every review.
Type "clear"
Enter
Type "dna show m_d90db5d8f27a --format text"
Sleep 400ms
Enter
Sleep 6s

# 4. Three months later the old mistake comes back, and DeutschLoop notices.
Type "clear"
Enter
Type "dna show m_f73a2424acc8 --format text"
Sleep 400ms
Enter
Sleep 7s
