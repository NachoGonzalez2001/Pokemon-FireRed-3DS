"""Where is the game stuck? Talk GDB's remote protocol to Azahar's gdbstub:
continue, wait, interrupt, then for every thread print PC/LR and the words on
its stack that fall in the executable's text, resolved with addr2line (a
heuristic backtrace: no unwinder, no Python in devkitARM's GDB).

usage: python rsp_hang.py ELF [SECONDS] [PORT]
Azahar must run with use_gdbstub=true (it waits for this client at boot).
"""
import socket
import subprocess
import sys
import time

ELF = sys.argv[1]
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 100
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 24689
A2L = r"C:\devkitPro\devkitARM\bin\arm-none-eabi-addr2line.exe"
NM = r"C:\devkitPro\devkitARM\bin\arm-none-eabi-nm.exe"

s = socket.create_connection(("127.0.0.1", PORT), timeout=30)


def send(cmd):
    body = cmd.encode()
    s.sendall(b"$" + body + b"#" + b"%02x" % (sum(body) & 0xFF))


def recv():
    buf = b""
    while True:
        c = s.recv(1)
        if not c:
            raise EOFError
        if c == b"+":
            continue
        if c == b"$":
            break
    while not buf.endswith(b"#"):
        buf += s.recv(1)
    s.recv(2)
    s.sendall(b"+")
    return buf[:-1].decode(errors="replace")


def cmd(c):
    send(c)
    return recv()


# text range from the symbol table
text_lo, text_hi = 0xFFFFFFFF, 0
for line in subprocess.run([NM, "-n", ELF], capture_output=True, text=True).stdout.splitlines():
    parts = line.split()
    if len(parts) == 3 and parts[1] in "tT":
        a = int(parts[0], 16)
        text_lo, text_hi = min(text_lo, a), max(text_hi, a)

print("halted at connect:", cmd("?"))
send("c")
time.sleep(WAIT)
s.sendall(b"\x03")
print("stop:", recv())

threads = []
r = cmd("qfThreadInfo")
while r.startswith("m"):
    threads += r[1:].split(",")
    r = cmd("qsThreadInfo")
print("threads:", threads)


def le32(hexstr, i):
    return int.from_bytes(bytes.fromhex(hexstr[i * 8:i * 8 + 8]), "little")


def a2l(addrs):
    out = subprocess.run([A2L, "-f", "-e", ELF] + ["0x%x" % a for a in addrs], capture_output=True, text=True).stdout
    lines = out.splitlines()
    return [(lines[2 * i], lines[2 * i + 1].split("/")[-1]) for i in range(len(addrs))]


for t in threads:
    cmd("Hg" + t)
    regs = cmd("g")
    pc, lr, sp = le32(regs, 15), le32(regs, 14), le32(regs, 13)
    print("\n== thread %s pc=%08x lr=%08x sp=%08x" % (t, pc, lr, sp))
    for (fn, loc), a in zip(a2l([pc, lr]), [pc, lr]):
        print("   %08x %s %s" % (a, fn, loc))
    mem = cmd("m%x,%x" % (sp, 0x400))
    if mem.startswith("E") or len(mem) < 8:
        continue
    words = [le32(mem, i) for i in range(len(mem) // 8)]
    cands = [w for w in words if text_lo <= (w & ~1) <= text_hi]
    seen = 0
    for (fn, loc), a in zip(a2l(cands), cands) if cands else []:
        print("   stack %08x %s %s" % (a, fn, loc))
        seen += 1
        if seen >= 24:
            break
s.close()
