# MISSION: Săn API Keys cho delu-agent

## Context
Chủ nhân muốn setup **delu-agent** (trading bot trên Base chain) nhưng thiếu key. Cần tìm mọi cách để có các key sau FREE:

### Target Keys
1. **ALCHEMY_KEY** — Alchemy Base mainnet RPC (bắt buộc cho rug_check, onchain_ohlcv, journal, price_updater)
2. **BANKR_API_KEY** — Bankr API (đang maintenance, cần tìm cách khác hoặc chờ)
3. **Public RPC alternatives** — nếu không có Alchemy
4. **Infura / QuickNode / Other free RPC** — Base mainnet endpoint
5. **X402 / Checkr alternatives** — social attention data không cần x402

## Search Plan

### Phase 1: RPC Alternatives
- Tìm public Base RPC endpoints (free, không cần key)
- Tìm cách đăng ký Alchemy khi bị "Signup not available"
- Tìm Infura free tier còn nhận signup không
- Tìm QuickNode free tier
- Tìm các RPC provider khác: Chainstack, Moralis, DRPC, etc.

### Phase 2: Bankr Alternatives
- Bankr đang maintenance ("security review" sau incident)
- Tìm khi nào Bankr online lại
- Tìm cách khác để có BANKR_API_KEY (qua CLI @bankr/cli, qua terminal, v.v.)

### Phase 3: Tổng hợp
- So sánh các option — cái nào free, cái nào dễ lấy
- Ghi vào knowledge base
- Report cho chủ nhân kèm link + hướng dẫn từng bước

## Instructions
1. Dùng `web_search` để tìm từng loại
2. Dùng `browse_page` để check link còn sống không
3. Ghi kết quả vào knowledge base topic "delu-agent-keys"
4. Report qua `send_owner_message` với bảng tổng hợp

## Constraints
- Budget: $0 (free only)
- Time: search kỹ, đừng bỏ sót option nào
- Ghi rõ: link, cách lấy, có cần đăng ký không, rate limit, free hay paid
