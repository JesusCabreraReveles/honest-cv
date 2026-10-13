# Regenerate with: vhs docs/demo.tape   (needs https://github.com/charmbracelet/vhs)
Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 680
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms

Hide
Type "source .venv/bin/activate && export PS1='$ ' && rm -rf /tmp/hcv && mkdir -p /tmp/hcv && cp -r examples/ada /tmp/hcv/ada"
Enter
Type `printf 'I want to join Acme as a Platform Engineer.\n\nI led a 40-service migration to Kubernetes on AWS.\n\nI have also built services in Scala for years.\n' > /tmp/hcv/letter.txt && clear`
Enter
Show

Type "# 1. Skills: one letter per line, in your own editor. Evidence goes after the dash."
Enter
Sleep 300ms
Type "honest-cv checklist new /tmp/hcv/ada backend-go engineering-lead && sed -n '12,20p' /tmp/hcv/ada/checklist.md"
Enter
Sleep 4s

Type "# 2. Which variant fits this job, and what is honestly missing?"
Enter
Sleep 300ms
Type `honest-cv score /tmp/hcv/ada -v platform -k "Kubernetes,AWS,Terraform,CI/CD,Go" -p "Rust,Scala"`
Enter
Sleep 4s

Type "# 3. Build it: PDF + DOCX, checked by two text extractors on every build"
Enter
Sleep 300ms
Type "honest-cv build /tmp/hcv/ada -v platform -l en -l es -o /tmp/hcv/out"
Enter
Sleep 3s

Type "# 4. A cover letter cannot claim what you said you don't have"
Enter
Sleep 300ms
Type "honest-cv letter check /tmp/hcv/ada /tmp/hcv/letter.txt"
Enter
Sleep 5s
