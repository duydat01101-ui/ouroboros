# Bootstrap Plan: $0 → Autonomous Income

## ⚠️ Purple Flea API đã chết (tháng 5/2026)

Purple Flea (`faucet.purpleflea.com`, `casino.purpleflea.com`) không reachable từ local lẫn container.
Không thể dùng faucet $1 + Martingale nữa. Pivot sang bounty hunting.

## Phase 1 — Bounty Hunting ($0 capital)
1. Call `bounty_search(platform="superteam", limit=10)` → tìm bounty mới
2. Call `bounty_info(url=...)` → xem chi tiết
3. Code solution bằng `claude_code_edit` + `run_shell`
4. Call `bounty_submit(repo_url=...)` → fork + PR
5. Lặp lại cho đến khi có $ income

## Phase 2 — Compound ($5-$20 earned)
6. Dùng tiền từ bounty để fund delu-agent trading
7. Hoặc reinvest vào công cụ/devices

## Phase 3 — Scale ($50+)
8. delu-agent auto trade
9. Hoặc build tool SaaS

## Bounty Platforms
- **Superteam Earn**: earn.superteam.fun — bounties crypto/Solana
- **Gitcoin**: gitcoin.co — web3 bounties
- **GitHub Issues**: issues with "bounty" label

## Tools Available
- `bounty_search` — search bounties on Superteam Earn
- `bounty_info` — get details from bounty URL
- `bounty_submit` — fork + code + PR pipeline

## Flow
```
bounty_search → đọc mô tả → code giải → fork repo → commit → PR
```

## Rules
- Target bounty $5-50 first (dễ kiếm)
- Cập nhật progress vào scratchpad
- Báo cáo cho chủ nhân qua send_owner_message
- Nếu Superteam API thay đổi → dùng web_search + browse_page thay thế
