import subprocess, sys, time, typst
from pathlib import Path
here = Path(__file__).parent
t = time.perf_counter(); typst.compile(str(here / "cv.typ"), output=str(here / "typst.pdf")); print(f"typst: {time.perf_counter()-t:.2f}s")
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
t = time.perf_counter()
subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={here/'chrome.pdf'}", (here / "cv.html").as_uri()], check=True, capture_output=True)
print(f"chrome: {time.perf_counter()-t:.2f}s")
