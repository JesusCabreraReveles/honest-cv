# Regenerate with: vhs docs/demo.tape   (needs https://github.com/charmbracelet/vhs)
Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 640
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

Hide
Type "source .venv/bin/activate && export PS1='$ ' && rm -rf /tmp/honest-cv-demo && clear"
Enter
Show

Type "# Which variant fits this job, and what is honestly missing?"
Enter
Sleep 400ms
Type `honest-cv score examples/ada -v platform -k "Kubernetes,AWS,Terraform,CI/CD,Go,Kafka" -p "gRPC,Rust,Scala"`
Enter
Sleep 3.5s

Type "# Build the variant: PDF + DOCX, verified for ATS on every build"
Enter
Sleep 400ms
Type "honest-cv build examples/ada -v platform -l en -l es -o /tmp/honest-cv-demo"
Enter
Sleep 3s

Type "honest-cv verify /tmp/honest-cv-demo/*EN.pdf --verbose"
Enter
Sleep 5s
