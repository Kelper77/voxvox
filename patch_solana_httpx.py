import solana.rpc.providers.http
import pathlib, sys

path = pathlib.Path(solana.rpc.providers.http.__file__)
text = path.read_text()
if "proxy=proxy" in text:
    new = text.replace("proxy=proxy", "")
    path.write_text(new)
    print("✅ Patched Solana SDK proxy argument removed")
else:
    print("ℹ️ No proxy=proxy found — already patched or compatible")
