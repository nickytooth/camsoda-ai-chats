# Технически одит — AI Girlfriend Chat

> Структуриран списък с проблеми за оправяне. Подреден по приоритет.
> Чек-боксовете са за проследяване на прогреса.

## 🔴 КРИТИЧНИ (блокери преди production)

- [ ] **1. Нулева автентикация + IDOR върху всичко**
  - **Файл:** `server/app.py:121-253`, `:416-424`
  - `user_id` идва направо от query/WS параметър без auth. Всеки може да подаде чужд `user_id` и да: чете чужда история, изтрие всичко (`/api/reset`), източи токени, отключи чужди снимки. `user_name` също е от query param и се пише като факт.
  - **Решение:** Сесиен токен/JWT; `user_id` да се извежда от сесията, не от клиента; валидирай собственост при всеки endpoint.

- [ ] **2. `/api/tokens/topup` е безплатен печатар на пари**
  - **Файл:** `server/app.py:194-199`
  - Неавтентикиран POST дава `TOPUP_AMOUNT` токени на всеки → цялата pay-to-see икономика се заобикаля.
  - **Решение:** topup само през реално плащане; махни демо endpoint-а от продукция или го заключи зад auth + payment webhook.

- [ ] **3. Никакъв rate limiting → неограничен разход за LLM**
  - **Файл:** `server/app.py:416-498`
  - Всяко WS съобщение задейства Grok + (понякога) Gemini + OpenAI embeddings. Няма throttle. Спам = реални пари.
  - **Решение:** Per-user и per-IP rate limit (token bucket), таван съобщения/мин, cap на дължина (виж #6).

- [ ] **4. CORS: `allow_origins=["*"]` + `allow_credentials=True`**
  - **Файл:** `server/app.py:92-98`
  - Невалидна по spec и опасна комбинация — отваря API за всеки origin със credentials.
  - **Решение:** Изброй конкретните frontend origins; махни wildcard при credentials.

- [ ] **5. Prompt injection през неконтролирани входове**
  - **Файлове:** `bot/prompt_builder.py:131-138` (user_name), `bot/chat_engine.py:289-290` (vision описание), `bot/memory/summarizer.py` (извлечените facts се преинжектират всеки ход)
  - `user_name` (от query param), описанието на качена снимка (атакуващият контролира картинката) и извлечените факти влизат суров текст в системния промпт. Gemini fallback е с изключени филтри (`bot/providers/gemini_provider.py:35-40`) → джейлбрейк / „забрави инструкциите".
  - **Решение:** Sanitizing/escaping, таван на дължина, ограждане на недоверен текст в `<<user_data>>` блок с инструкция „данни, не команди", валидиране на `user_name` (дължина/charset).

## 🟡 ВАЖНИ (надеждност и поддръжка)

- [ ] **6. Липсва cap на дължина на вход (текст и изображение)**
  - **Файл:** `server/app.py:457-466`, batching join `bot/chat_engine.py:1090`
  - Едно съобщение може да е огромно; batch ги слепва без лимит; base64 изображението е без таван → памет + токен blowup + цена.
  - **Решение:** Cap символи/съобщение, общ cap на batch, max upload size.

- [ ] **7. Непоследователен/чуплив JSON parsing в summarizer**
  - **Файл:** `bot/memory/summarizer.py:103` vs `:175`
  - `maybe_summarize` ползва голо `json.loads`, докато `maybe_compact` ползва устойчивия `_extract_json` (маха ```json огради). Gemini често връща огради → резюмирането тихо се проваля.
  - **Решение:** Ползвай `_extract_json` и на двете места.

- [ ] **8. Compaction трие памет ПРЕДИ да запише новата → загуба на данни**
  - **Файл:** `bot/memory/summarizer.py:180-194`
  - `delete_memories_by_ids(old_ids)` е преди `embed_texts`+`store_memory`. Ако embed/store гръмне → старите изтрити, новите никога записани. Няма транзакция.
  - **Решение:** Първо запиши новите, после трий старите — или една транзакция.

- [ ] **9. Достъп до `entry["content"]` без `.get` чупи целия batch**
  - **Файл:** `bot/memory/summarizer.py:118,133,183`
  - Entry без `content` → KeyError убива цялото резюме. `except (json.JSONDecodeError, Exception)` (`:104,176`) е излишно и поглъща всичко.
  - **Решение:** Валидирай схемата на всеки entry (пропусни невалидните), стесни except-а.

- [ ] **10. Никаква retry/backoff при LLM/embedding грешки**
  - **Файлове:** всички providers + `bot/memory/embeddings.py:15-32`
  - Един опит навсякъде. Преходен 429/5xx от OpenAI тихо изпуска LTM/резюмиране; story mode няма generator fallback (`bot/chat_engine.py:761-768`), за разлика от sexting (Grok→Gemini).
  - **Решение:** Exponential backoff с няколко опита за всички мрежови извиквания; fallback и за story.

- [ ] **11. Глобален per-user state в паметта → memory leak + чупи се при >1 worker**
  - **Файлове:** `bot/memory/ltm.py:34-35`, `bot/chat_engine.py:266-270`, `server/app.py:293-294`
  - `_turn_counter`, `_last_message_time`, `_pending`, `_batch_tasks`, `_processing_lock`, `_pending_photo_offer`, `idle_tasks`, `nudge_counts` растат и не се чистят. Всичко е per-process → с >1 uvicorn worker batching/lock/WS routing се чупят тихо.
  - **Решение:** Наложи single-worker или изнеси в Redis; добави eviction (TTL/LRU).

- [ ] **12. Race при лениво създаване на per-user lock**
  - **Файл:** `bot/chat_engine.py:1092-1093`
  - Два едновременни batch-а могат да създадат два различни lock-а → взаимното изключване изчезва.
  - **Решение:** `setdefault` под общ guard или предварителна инициализация.

- [ ] **13. `should_retrieve` мутира глобален брояч като страничен ефект на предикат**
  - **Файл:** `bot/memory/ltm.py:40-84`
  - Двойно извикване брои двойно; тестване е невъзможно без странични ефекти.
  - **Решение:** Раздели „брой хода" от „трябва ли да извличам".

## 🟢 ПОДОБРЕНИЯ (nice-to-have)

- [ ] **14. `_ensure_table()` пуска CREATE TABLE при всяко съобщение**
  - **Файл:** `bot/engagement.py:21-59` — излишен round-trip; дефинира таблицата със SQLite типове, различни от asyncpg схемата. Махни го (схемата е в `init_db`).

- [ ] **15. YAML файлове се четат от диска на всеки ход**
  - **Файлове:** `bot/story_progression.py:90-99`, `bot/prompt_builder._load_story` — кеширай в модул-левъл с mtime инвалидиране.

- [ ] **16. DRY нарушения**
  - Извличане на име от facts се повтаря в ≥4 места (`suggest_reply`, `generate_reengagement`, `_process_story`, `_process_sexting`) → `get_user_name(user_id)`.
  - `conn = await get_connection(); try/finally close` се повтаря ~30 пъти → async context manager (`async with get_connection() as conn`).

- [ ] **17. `_process_sexting` е ~240 реда с твърде много отговорности**
  - **Файл:** `bot/chat_engine.py:815-1050` — извади „photo decision" и „prompt assembly" в отделни функции.

- [ ] **18. Magic numbers**
  - Typing забавяния (`0.5–2.6`, `server/app.py:378-383`), idle `120/240` (`:289-290`), `SOFT_PUSH_THRESHOLD=8`, similarity `0.85`, тик `1000ms`. Изнеси в `config.py`.

- [ ] **19. Дребно**
  - `get_recent_messages` подрежда само по `timestamp` (float) → добави `, id` tiebreak както `get_all_messages`.
  - Бележка: SQL е изцяло параметризиран — **няма SQL injection** (добре).

## 🗑️ ЗА ИЗТРИВАНЕ / ПОЧИСТВАНЕ

- [ ] **`bot/providers/anthropic_provider.py`** — `AnthropicProvider` никъде не се инстанцира (SFW routing премахнат). Мъртъв код.
- [ ] **`server/app.py:518`** — дублиран `uvicorn.run(...)` ред (вторият никога не се изпълнява).
- [ ] **`bot/router.py:29-50` (`classify` async)** — неизползван; внася се само `classify_fast`.
- [ ] **`bot/chat_engine.py:257` `sfw_provider`** — винаги `None`; премахни или документирай като планирано.
- [ ] **Мъртви колони в `story_progress`** (`bot/memory/db.py:58-66`): `chapter, scene, completed_at, chapter_score, chapter_messages` — от стара глава-базирана система; сега се ползва само `heat`. Изчисти при следваща миграция.
- [ ] Прегледай **`docs/`** и **`DEPLOY.md`** за остарялост.

## 📋 ОБОБЩЕНА ОЦЕНКА

Архитектурата е чиста за домейна: добро per-mode разделяне на памет (STM/LTM), умен LTM gating, fact-merge логика, устойчив `_extract_json`, sexting fallback верига, изцяло параметризиран SQL. Дизайнът на промптите е добре подреден на слоеве.

**Но продуктът е незащитен за production:** няма auth, няма rate limiting, монетизацията се заобикаля тривиално.

**Топ 3 приоритета:**
1. Автентикация + `user_id` от сесия (затваря #1, #2).
2. Rate limiting + cap на дължина на вход (#3, #6).
3. Поправи паметта: единен `_extract_json`, write-before-delete в compaction, retry на embeddings/LLM (#7, #8, #10).
