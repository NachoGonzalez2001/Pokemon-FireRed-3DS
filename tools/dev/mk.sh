#!/bin/bash
# mk.sh <logname> <make args...>: run make in the port dir, log, summarize errors
cd /c/fr3ds/upstream/3ds_port
log=/c/fr3ds/$1.log; shift
make "$@" > "$log" 2>&1
code=$?
echo "make exit=$code"
grep -E "error:|undefined reference|Error:|multiple definition|\*\*\*" "$log" \
  | sed -E 's/^.*(src\/|include\/|data\/)/\1/' | sed -E 's/^.*: (undefined reference to)/\1/' \
  | cut -c1-200 | sort | uniq -c | sort -rn | head -n 60
