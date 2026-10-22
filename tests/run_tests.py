"""Run JS tests using Node when available, or macOS's JavaScriptCore framework."""
import ctypes
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / 'index.html').read_text()
inline = '\n'.join(re.findall(r'<script>(.*?)</script>', html, re.S))
script = (
    'globalThis.window = {};\n'
    + 'const PAGE_SCRIPT = ' + json.dumps(inline) + ';\n'
    + 'const TEST_CSV = ' + json.dumps((ROOT / 'registrations.csv').read_text()) + ';\n'
    + (ROOT / 'admission-store.js').read_text() + '\n'
    + (ROOT / 'tests/admission-store.test.js').read_text()
)

if shutil.which('node'):
    with tempfile.NamedTemporaryFile(suffix='.js', mode='w') as f:
        f.write(script + '\nsetTimeout(() => { console.log(JSON.stringify(testResult)); '
                'process.exit(testResult?.passed ? 0 : 1); }, 0);')
        f.flush()
        subprocess.run(['node', f.name], check=True)
else:
    j = ctypes.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/JavaScriptCore')
    p = ctypes.c_void_p
    for name, args, result in [
        ('JSGlobalContextCreate', [p], p),
        ('JSStringCreateWithUTF8CString', [ctypes.c_char_p], p),
        ('JSEvaluateScript', [p,p,p,p,ctypes.c_int,ctypes.POINTER(p)], p),
        ('JSValueToStringCopy', [p,p,ctypes.POINTER(p)], p),
        ('JSStringGetMaximumUTF8CStringSize', [p], ctypes.c_size_t),
        ('JSStringGetUTF8CString', [p,ctypes.c_char_p,ctypes.c_size_t], ctypes.c_size_t),
    ]:
        func = getattr(j, name)
        func.argtypes = args
        func.restype = result
    ctx = j.JSGlobalContextCreate(None)

    def evaluate(source):
        exception = p()
        value = j.JSEvaluateScript(ctx, j.JSStringCreateWithUTF8CString(source.encode()),
                                   None, None, 1, ctypes.byref(exception))
        string = j.JSValueToStringCopy(ctx, exception.value or value, None)
        buf = ctypes.create_string_buffer(j.JSStringGetMaximumUTF8CStringSize(string))
        j.JSStringGetUTF8CString(string, buf, len(buf))
        text = buf.value.decode()
        if exception.value:
            raise RuntimeError(text)
        return text

    evaluate(script)
    result = json.loads(evaluate('JSON.stringify(globalThis.testResult)'))
    if not result or 'error' in result:
        raise RuntimeError(result)
    print(json.dumps(result, indent=2))
