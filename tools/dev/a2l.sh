cd /c/fr3ds/upstream/3ds_port
for a in "$@"; do
  arm-none-eabi-addr2line -f -i -C -e firered3ds.elf "$a"
done
