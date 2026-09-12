#!/usr/bin/env bash
# GLHAC 홈페이지 배포 — 가비아 서버 /var/www/glhac-home
#
# 겪은 함정들을 스크립트에 박아 둔다:
#   · 소유권을 root 로 바꾸면 nginx 가 못 읽는다 → rocky:rocky
#   · SELinux 라벨(restorecon)을 빠뜨리면 403 이 난다
#   · /assets/ 는 1년 immutable 캐시다 — 번들 내용만 바꾸고 파일명을 그대로 두면
#     이미 방문한 브라우저가 옛 파일을 계속 쓴다. 아래에서 그걸 잡아낸다.
set -euo pipefail

KEY="${GLHAC_SSH_KEY:-$HOME/Downloads/SSH_KeyPair-260908134815.pem}"
HOST="${GLHAC_SSH_HOST:-rocky@1.201.116.174}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE=/var/www/glhac-home
OWNER=rocky:rocky

DRY=0; ROLLBACK=0
for a in "$@"; do
  case "$a" in
    --dry-run)  DRY=1 ;;
    --rollback) ROLLBACK=1 ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "모르는 옵션: $a"; exit 2 ;;
  esac
done

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST")
RS="ssh -i $KEY -o StrictHostKeyChecking=no"
TS="$(date +%Y%m%d%H%M%S)"
say() { printf '  %s\n' "$*"; }

if [ "$ROLLBACK" = 1 ]; then
  say "직전 백업으로 되돌립니다"
  "${SSH[@]}" bash -se <<'EOS'
set -euo pipefail
LAST=$(ls -t /opt/glhac-home-bak-*.tgz 2>/dev/null | head -1)
[ -n "$LAST" ] || { echo "  되돌릴 백업이 없습니다"; exit 1; }
echo "  사용할 백업: $LAST"
sudo rm -rf /var/www/glhac-home
sudo tar xzf "$LAST" -C /var/www
sudo chown -R rocky:rocky /var/www/glhac-home
sudo restorecon -R /var/www/glhac-home 2>/dev/null || true
EOS
  say "되돌리기 완료 — $(curl -s -o /dev/null -w '%{http_code}' https://glhac.com/)"
  exit 0
fi

[ -f "$KEY" ] || { echo "SSH 키가 없습니다: $KEY"; exit 1; }

# 번들을 고쳤는데 파일명이 그대로면 캐시가 옛 것을 준다 — 미리 잡는다
bundle=$(ls "$SRC"/assets/index-*.js 2>/dev/null | head -1)
if [ -n "$bundle" ]; then
  live=$(curl -s https://glhac.com/ | grep -oE 'assets/index-[a-z0-9]+\.js' | head -1)
  if [ -n "$live" ] && [ "assets/$(basename "$bundle")" = "$live" ]; then
    if ! curl -s "https://glhac.com/$live" | cmp -s - "$bundle"; then
      echo "  ⚠ 번들 내용이 다른데 파일명이 같습니다: $(basename "$bundle")"
      echo "    /assets/ 는 1년 immutable 캐시라 방문자가 옛 파일을 계속 씁니다."
      echo "    파일명을 바꾸고 index.html 의 참조도 함께 고치세요."
      exit 1
    fi
  fi
fi

say "대상 $HOST:$REMOTE"
rsync -az --delete --dry-run --itemize-changes -e "$RS" \
  --exclude '.git' --exclude '.DS_Store' --exclude 'scripts' --exclude 'tools' \
  --exclude 'README.md' --exclude '.github' --exclude '.gitignore' \
  "$SRC/" "$HOST:/tmp/web-$TS/" 2>/dev/null | grep -vE '^\.d|^$' | head -20 || true
if [ "$DRY" = 1 ]; then say "dry-run — 아무것도 바꾸지 않았습니다"; exit 0; fi

say "백업"
"${SSH[@]}" "sudo tar czf /opt/glhac-home-bak-$TS.tgz -C /var/www glhac-home
             ls -t /opt/glhac-home-bak-*.tgz | tail -n +11 | xargs -r sudo rm -f"

say "전송"
rsync -az -e "$RS" --exclude '.git' --exclude '.DS_Store' --exclude 'scripts' \
  --exclude 'tools' --exclude 'README.md' --exclude '.github' --exclude '.gitignore' \
  "$SRC/" "$HOST:/tmp/web-$TS/"

say "적용"
"${SSH[@]}" bash -se <<EOS
set -euo pipefail
sudo rsync -a /tmp/web-$TS/ $REMOTE/
sudo chown -R $OWNER $REMOTE           # root 로 두면 nginx 가 못 읽는다
sudo restorecon -R $REMOTE 2>/dev/null || true   # 라벨 없으면 403
rm -rf /tmp/web-$TS
EOS

say "── 확인 ──"
fail=0
for u in https://glhac.com/ https://glhac.com/board/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$u")
  say "$u → $code"
  [ "$code" = "200" ] || fail=1
done
[ "$fail" = 0 ] || { echo "  ❌ 확인 실패 — bash scripts/deploy.sh --rollback"; exit 1; }
say "배포 완료 (백업 태그 $TS)"
