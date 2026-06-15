# Sexting Mode — пълно обяснение на прост език

Този документ описва как работи **Sexting mode** в проекта — от момента, в който потребителят изпрати съобщение, до момента, в който Victoria върне отговор във frontend-а.

> **ВАЖНО (актуализирано):** Старата 3-степенна intimacy система (stages 1→2→3) е **премахната**. Victoria вече е **една, винаги отворена persona** (`victoria1.yaml`). Всичко минава през Grok. Запазен е само лек **mood** слой, който оцветява тона й. Този документ отразява новата архитектура.

Целта е да е ясно:

- **какво влиза в backend-а**
- **коя persona се ползва** (вече само една)
- **кога е SFW и кога NSFW** (и защо вече не сменя модела)
- **как работи signal scoring + mood**
- **какво точно отива като system message към LLM-а**
- **как работи memory системата**
- **как се оформят отговорите като chat bubbles**
- **как работят снимките**
- **какво реално е имплементирано и какво само е подготвено**

---

## 1. Голямата картина

Sexting mode е основният chat режим, в който Victoria говори като реален човек в чат.

Той не работи като обикновен chatbot, който веднага отговаря на всяко съобщение. Вместо това backend-ът прави няколко неща:

1. Приема съобщението през WebSocket.
2. Ако потребителят е пратил снимка, анализира я с Grok Vision.
3. Записва съобщението в short-term memory.
4. Събира няколко бързи съобщения в batch.
5. След кратко изчакване обработва всички натрупани съобщения заедно.
6. С **един Gemini call** оценява съобщението: signals (charm/respect/humor/hostility/pushing) **и** дали е NSFW.
7. Обновява краткотрайния **mood** на Victoria от тези signals.
8. Сглобява system prompt + memory + последни съобщения.
9. Изпраща prompt-а към **Grok**.
10. Записва отговора в базата.
11. Разделя отговора на отделни chat bubbles.
12. Изпраща ги през WebSocket с typing indicator и паузи.

На прост език: **Victoria не е само един prompt**. Отговорът й е резултат от persona + текущ mood + история + дългосрочна памет + facts + time-of-day context.

---

## 2. Къде започва всичко

Основният вход за чата е WebSocket endpoint-ът:

```text
server/app.py
/ws/chat
```

Когато frontend-ът се свърже, URL-ът съдържа `user_id` и (по избор) `user_name`:

```text
/ws/chat?user_id=12345&user_name=Nicky
```

При свързване backend-ът **записва името като fact**, така че Victoria знае с кого говори:

```python
if user_name:
    await upsert_fact(user_id, "name", user_name)
```

Когато frontend-ът изпрати съобщение, backend-ът получава JSON:

```json
{
  "type": "message",
  "mode": "sexting",
  "content": "...",
  "image": "optional_base64_image"
}
```

В `server/app.py` backend-ът гледа `mode`:

- ако `mode == "story"` → минава през Story pipeline
- иначе → минава през Sexting pipeline

За sexting се извиква:

```text
engine.process_sexting_batched(...)
```

Това е важно: **sexting mode е batched**, не директен.

---

## 3. Какво значи batching

Batching означава, че Victoria не отговаря веднага на всяко отделно съобщение.

Ако потребителят напише:

```text
hey
what are you doing
missed you
```

и ги изпрати бързо едно след друго, backend-ът ги събира и ги обработва като един вход.

Това става в:

```text
bot/chat_engine.py
process_sexting_batched()
_batch_collect()
```

### Защо е направено така

За да се усеща като реален chat:

- реален човек чете няколко бързи съобщения заедно
- не отговаря роботизирано на всяко поотделно
- има кратко забавяне, сякаш мисли/пише

### Как работи технически

За всеки `user_id` има buffer `self._pending[user_id]`. Всяко входящо sexting съобщение се добавя там. Ако няма стартиран batch task, backend-ът стартира `_batch_collect()`, който:

1. изчислява delay между `MIN_RESPONSE_DELAY` и `MAX_RESPONSE_DELAY`
2. ограничава delay-а до максимум 15 секунди
3. изчаква
4. взима всички pending съобщения
5. маха последователно повтарящи се еднакви съобщения
6. събира ги с нов ред
7. праща ги към `_process_sexting()`

---

## 4. Първо записване в memory

Още преди batch-ът да се обработи, user message се записва в базата:

```text
messages table
role = "user"
mode = "sexting"
```

Това става в `bot/memory/stm.py` → `add_message()`.

Причината е проста: ако user-ът refresh-не страницата, смени mode или WebSocket-ът падне, съобщението вече е запазено. Това е short-term memory — STM.

---

## 5. Основният sexting pipeline

След batching-а се извиква `_process_sexting()` в `bot/chat_engine.py`. Това е сърцето на sexting mode. Там се случват следните неща:

1. Summarization/compaction на memory, ако е време.
2. Взимане на последните съобщения от STM.
3. **Signal scoring + NSFW класификация** (един Gemini call).
4. Tracking на engagement.
5. Обновяване на mood.
6. LTM retrieval.
7. Soft-push hint, ако е време.
8. Взимане на user facts.
9. Build prompt.
10. Generate response (Grok).
11. Запис на assistant response.
12. Split на response-а на bubbles.

---

## 6. Една persona (always open)

Вече има **само една активна** persona за sexting:

```text
personas/victoria1.yaml
```

Конфигурира се в `bot/config.py`:

```python
PERSONA_FILE_SEXTING = BASE_DIR / "personas/victoria1.yaml"
```

`victoria1.yaml` съдържа:

- identity, възраст, tagline
- physical description, voice, scent
- communication style, linguistic markers, pet names
- background
- core memories (sexual + non-sexual)
- opening lines (референция към Emma)
- **`dynamic`** — текущата релационна/сексуална динамика
- boundaries / hard rules

### Полето `dynamic`

Това замества старите `stage_instructions`. То казва на модела как се държи Victoria — **напълно отворена от първото съобщение**:

```text
FULLY OPEN, FROM THE FIRST MESSAGE. No slow burn, no deflection.
She already wants you and she's done pretending otherwise.
- She is openly, unapologetically attracted to you...
- She LEADS and PROVOKES...
- She's also warm and motherly...
- explicit when hot, but always elegant — filthy in perfect grammar...
```

`dynamic` се рендира в system prompt-а от `persona.to_system_prompt()` като секция `CURRENT DYNAMIC:`.

> Старите файлове `victoria.yaml` и `victoria_nsfw.yaml` още съществуват в репото, но **не се ползват** от sexting flow-а.

---

## 7. Как се зарежда persona-та

При startup на backend-а в `server/app.py`:

```python
persona = load_persona(PERSONA_FILE_SEXTING)   # victoria1.yaml
nsfw_persona = persona                          # същата persona
```

След това се създава `ChatEngine` с:

```text
persona      = victoria1.yaml
nsfw_persona = victoria1.yaml   (същата)
sfw_provider = AnthropicProvider()   # Claude — само fallback
nsfw_provider = GrokProvider()       # Grok — основният
classifier_provider = GeminiProvider()  # Gemini — signals + classify
vision_provider = GrokProvider()        # Grok — vision
```

---

## 8. Как се избира provider/persona

Вече **няма stage логика**. Правилото е тривиално:

```python
# Victoria е винаги напълно отворена
provider = self.nsfw_provider          # Grok
active_persona = self.nsfw_persona or self.persona  # victoria1
```

Всяко sexting съобщение минава през **Grok** с отворената persona. Claude се ползва **само** ако Grok хвърли грешка (fallback).

---

## 9. SFW/NSFW classification + signal scoring (един call)

Преди класификацията беше отделен Gemini call. **Сега е слята** в signal scoring-а — един Gemini call връща и двете.

### Стъпка 1 — безплатен keyword fast-path

`bot/router.py` → `classify_fast()` проверява за явни NSFW ключови думи чрез regex. Ако има match → веднага `nsfw`, без LLM.

### Стъпка 2 — Gemini signal eval (включва nsfw флаг)

`bot/intimacy.py` → `evaluate_message()` праща един prompt към Gemini, който връща JSON:

```json
{
  "nsfw": true,
  "charm": 2,
  "respect": 1,
  "humor": 0,
  "hostility": 0,
  "pushing": 0,
  "reasoning": "..."
}
```

В `_process_sexting()`:

```python
signals = await evaluate_message(user_id, text, _llm_call)   # 1 Gemini call
fast = classify_fast(text)                                   # безплатен regex
classification = fast or ("nsfw" if signals.get("nsfw") else "sfw")
```

### Важно за scoring правилата

Понеже Victoria е винаги отворена, prompt-ът **не наказва** сексуалния интерес:

- `hostility` (0–10) се вдига само за истински груб/обиден език (обиди, slurs) — **не** за нормален sexual talk; 0 = нормално, 10 = много враждебно
- `respect` е негативно само за реално унизително държане
- `pushing` е негативно само при агресия/чувство за право

Тоест explicit съобщение от учтив потребител дава добри signals → mood става `aroused`, не `annoyed`.

---

## 10. Mood — краткотрайното емоционално състояние

Mood заменя старите stage instructions. Това е **бързо** състояние, което се мени на всяко съобщение и оцветява тона на Victoria.

Файл: `bot/mood.py`. Таблица: `mood_state` (`user_id`, `mood`, `intensity`, `updated_at`).

### 6-те настроения

| Mood | Кога | Поведение |
|---|---|---|
| **warm** | учтив, приятен чат (default) | отворена, нежна |
| **playful** | хумор, charm ≥3 | дразнеща, шеговита |
| **tender** | късно вечер + charm | по-мека, уязвима, интимна |
| **aroused** | NSFW класификация | губи композъра си, горещо |
| **distant** | скучни/generic съобщения | кратки отговори |
| **annoyed** | истински груб/обиден тон | елегантно раздразнена |

### Как се изчислява

`_derive_mood(signals, classification, time_period)` е чиста логика — **без допълнителен LLM call**. Ползва signals-ите от стъпка 9 + класификацията + часа от деня:

```python
if respect <= -3 or hostility >= 5:       return "annoyed", 3
if pushing <= -3 or hostility >= 2 or ...: return "distant", 2
if classification == "nsfw":              return "aroused", 3
if late_night and charm >= 1:             return "tender", 2
if humor >= 2 or charm >= 3:              return "playful", 2
if charm >= 1 and respect >= 0:           return "warm", 1
...
```

### Decay

Ако минат **30 минути** без съобщение, mood-ът се връща на `warm`.

### Инжектиране в prompt-а

`format_mood_for_prompt()` добавя един ред в system message-а:

```text
YOUR MOOD RIGHT NOW (playful): You're in a playful, teasing mood —
witty, light, a little mischievous. Let it colour your tone naturally —
don't announce it.
```

---

## 11. Какво точно отива като system message

System message се строи в `bot/prompt_builder.py` → `build_prompt()`.

На LLM-а се праща list от messages:

```python
[
  {"role": "system", "content": system_text},
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  ...
]
```

`system_text` е сглобен от следните секции (в ред):

### 1. Persona system prompt — `persona.to_system_prompt()`

- identity: име, възраст, tagline
- physical appearance, voice, scent
- communication style, linguistic markers, pet names
- background
- core memories (sexual + non-sexual)
- **CURRENT DYNAMIC** (от полето `dynamic`)
- boundaries / hard rules

### 2. User name

Ако има fact `name`:

```text
The user's name is Nicky. Use it naturally alongside your usual pet names.
```

### 3. Time-of-day context — `get_time_prompt()`

```text
RIGHT NOW: It's Monday, June 15, 5:30 PM in Miami.
You're home from work, pouring a glass of wine...
```

(+ weather, ако има `OPENWEATHER_API_KEY`.)

### 4. Texting style instructions (sexting mode)

```text
TEXTING STYLE — THIS IS A REAL CHAT, NOT AN ESSAY:
- пиши като реален човек на телефона
- никога не завършвай с period
- short/punchy lines, 1-3 messages всяко на свой ред
- no slang (u, lol), emojis рядко
```

### 5. Conversation continuity (ако вече е поздравила)

Понеже Victoria отваря разговора първа, тук ѝ се казва да **не** се поздравява пак, а да продължи нишката.

### 6. Mood line

Един ред с текущия mood (виж раздел 10).

### 7. Last-seen note

Колко време е минало от последното съобщение — за да реагира естествено.

### 8. Known facts

```text
Known facts about this person (use naturally, don't recite):
- name: Nicky
- location: ...
```

### 9. Long-term memories

```text
What you remember about this person:
- ...
```

или, ако няма: `You don't know anything about this person yet...`

### 10. Soft-push hint

Ако engagement системата реши, че е време:

```text
IMPORTANT FOR THIS REPLY: Naturally hint that you have private photos...
```

> Това е само текстов hint — **не** изпраща реална снимка.

---

## 12. Какво НЕ е system message

Последните user/assistant съобщения **не** са system message. Те се добавят след system message-а като нормални chat messages (conversation history от STM).

---

## 13. Memory системата

### STM — short-term memory

Таблица `messages` (`id`, `user_id`, `role`, `content`, `timestamp`, `mode`). `mode` е важно — `sexting` и `story` имат отделна история.

За prompt-а се взимат последните `STM_MAX_TURNS` turn-а:

```text
STM_MAX_TURNS = 18
get_recent_messages(user_id, STM_MAX_TURNS, mode="sexting")
```

### LTM — long-term memory

Таблица `memories` (`category`, `content`, `importance`, `embedding`, `created_at`, `last_accessed`). Пази обобщени memory entries с embeddings, не целия разговор.

### Facts — структурирани факти

Таблица `user_facts`. По-детерминистични от LTM — ако има fact `name`, той се inject-ва почти винаги. Тук се пази и името от WebSocket connect-а.

---

## 14. Как STM става LTM

При всяко `_process_sexting()` се проверява `maybe_summarize()`. Ако user turns ≥ `STM_MAX_TURNS` (18), най-старите `STM_SUMMARIZE_BATCH` (10) се пращат към Gemini за summarization. Gemini връща JSON с `memories` и `facts`. После backend-ът:

1. Прави embeddings на memory текстовете (OpenAI).
2. Проверява за сходна стара memory → update или нова.
3. Upsert-ва facts в `user_facts`.
4. Изтрива старите raw messages, които са вече summary-знати.

**Старите chat messages се компресират в memories и facts, за да не расте prompt-ът безкрайно.**

---

## 15. LTM retrieval — кога търси memory

Не всяко съобщение прави vector search (струва OpenAI embeddings call). `should_retrieve()` връща `true`, ако:

- user-ът казва `remember`, `you said`, `last time`, `earlier`
- съобщението е по-дълго от 30 символа
- минал е голям gap от последното съобщение
- всеки N-ти turn като fallback

При retrieval score-ът е:

```text
similarity * 0.5 + importance * 0.3 + recency * 0.2
```

Top `LTM_TOP_K = 5` влизат в prompt-а.

---

## 16. Engagement system

Отделна от signal/mood системата. Таблица `engagement_state` (`nsfw_count`, `total_messages`, `last_push_at`, `last_selfie_at`, `last_message_at`, `last_reengage_at`).

При всяко съобщение `track_message(user_id, classification)` увеличава `total_messages` и (ако NSFW) `nsfw_count`.

### Soft push

Ако `nsfw_count >= SOFT_PUSH_THRESHOLD` (8), backend-ът inject-ва soft-push hint. Това **не** праща снимка — само казва на Grok да намекне за private photos. След това `nsfw_count` се reset-ва.

### Re-engagement (double-text)

`generate_reengagement()` праща спонтанно follow-up съобщение, ако user-ът е онлайн но е утихнал. Ползва Grok + отворената persona + текущия mood.

---

## 17. Снимки от потребителя

User може да прати снимка като base64. Backend-ът я decode-ва и в `process_sexting_batched()` я подава на `vision_provider.analyze_image()` (Grok Vision). Резултатът се добавя към текста като:

```text
[User sent a photo: description]
```

LLM-ът не вижда директно снимката — вижда **текстово описание**.

---

## 18. Снимки/content от Victoria (подготвено, не активно)

Има подготовка (`CONTENT_DIR`, `/content` static, `sent_content`, `pending_unlocks`, `ChatResponse.content_urls`, `should_send_selfie()`), но **Victoria още не избира и не праща снимки автоматично** — `should_send_selfie()` не се вика в `_process_sexting()` и нищо не пълни `content_urls`.

---

## 19. Как се генерира отговорът

```python
prompt_messages = await build_prompt(...)
response_text = await provider.generate(prompt_messages)   # Grok
```

Ако Grok fail-не → fallback към Claude. Ако и той fail-не → връща `...`. Празен response → празен `ChatResponse`. При успех се записва целият текст в STM (`role=assistant`, `mode=sexting`) **преди** split на bubbles.

---

## 20. Chat bubbles

LLM-ът връща 1-3 кратки реда, разделени с newline. `_split_response()`:

1. заменя long dashes с normal dash
2. split-ва по `\n`
3. маха празните редове
4. връща list от strings — всеки става отделен bubble

---

## 21. Typing indicator и delays

`server/app.py` праща всяко bubble отделно: `typing_start` → random delay → `typing_end` → `message`. Между bubbles чака още 0.5–1.5 сек.

Delay според дължина:

```text
< 50 chars   → 1.0 - 2.5 sec
< 150 chars  → 2.0 - 4.0 sec
>= 150 chars → 3.0 - 6.0 sec
```

Има два вида забавяне: **batch collect delay** (преди LLM) и **typing delay** (след LLM).

---

## 22. Time-of-day система

`bot/time_context.py`, Miami timezone. Периоди: `early_morning`, `morning`, `afternoon`, `evening`, `night`, `late_night`. Всеки има mood, activity, energy, preferred_tags.

Влияе на: (1) **prompt-а** — какво прави Victoria сега; (2) **mood** — `late_night` + charm може да даде `tender`.

---

## 23. Базата данни — таблици за sexting

| Таблица | Роля |
|---|---|
| `messages` | raw chat history (STM, history endpoint) |
| `memories` | LTM с embeddings |
| `user_facts` | структурирани facts (вкл. name) |
| `mood_state` | текущ mood + intensity |
| `engagement_state` | counters за engagement / soft push |
| `sent_content` | подготвена, не активна |
| `pending_unlocks` | подготвена, не активна |

> Старата `intimacy_state` таблица вече **не се ползва** (stages са премахнати). Reset endpoint-ът все пак опитва да я изтрие, ако съществува от стари данни.

---

## 24. Кои модели за какво

### xAI Grok — основният
- генерира **всички** sexting отговори
- story mode отговори
- vision анализ на user снимки

### Google Gemini — помощникът
- signal scoring + NSFW класификация (**един** call на съобщение)
- STM → LTM summarization
- memory compaction
- story chapter progression

### Anthropic Claude — само fallback
- ползва се само ако Grok хвърли грешка

### OpenAI — само embeddings
- embed на user съобщения и memory entries за similarity search

---

## 25. Първо отваряне на sexting mode

При `GET /api/history/sexting`, ако няма messages, backend-ът seed-ва opening message:

```python
engine.persona.get_random_opening()   # от victoria1.yaml → opening_lines
```

Opening line-ът референцира Emma. Ако има няколко реда, всеки се записва като отделно assistant съобщение → отделни bubbles.

### Typing анимация при отваряне

Frontend-ът (`useChat.ts`) разпознава, че историята е само едно (или няколко) assistant съобщения = първо посещение, и показва **typing indicator ~1.5 сек** преди да ги покаже — за да изглежда, че Victoria тъкмо пише.

---

## 26. Reset

`POST /api/reset?user_id=X` трие user data от: `messages`, `memories`, `user_facts`, `sent_content`, `story_progress`, `engagement_state`, `intimacy_state` (последните се пропускат, ако таблицата липсва).

Frontend Reset бутонът също трие `localStorage` и връща потребителя на Name Screen. След reset историята е празна → нов opening message при следващо отваряне.

---

## 27. Целият pipeline в едно

```text
Frontend sends WebSocket message
        ↓
server/app.py receives it (+ saves user_name as fact on connect)
        ↓
if image: decode base64
        ↓
process_sexting_batched()
        ↓
if image: Grok Vision → text description
        ↓
save user message to STM
        ↓
add text to pending batch
        ↓
wait 3-10 sec, max 15 sec
        ↓
_process_sexting()
        ↓
maybe summarize old STM → LTM/facts
        ↓
get recent STM messages
        ↓
evaluate_message() → signals + nsfw  (1 Gemini call)
        ↓
classify = keyword fast-path OR signals.nsfw
        ↓
track engagement
        ↓
update_mood() from signals  (no extra LLM call)
        ↓
provider = Grok, persona = victoria1 (always)
        ↓
maybe retrieve LTM memories
        ↓
maybe add soft-push hint
        ↓
get user facts
        ↓
build system message (persona + dynamic + mood + facts + memories + time)
        ↓
append recent conversation messages
        ↓
call Grok (fallback Claude)
        ↓
save assistant response to STM
        ↓
split response by newline into bubbles
        ↓
send typing_start / typing_end / message events
        ↓
frontend renders bubbles
```

---

## 28. Current implementation status

### Работи в момента

- WebSocket chat (+ user_name → fact)
- Sexting batching
- Signal scoring + NSFW класификация в **един** Gemini call
- Mood система (6 настроения + decay)
- Always-open single persona (`victoria1.yaml`) през Grok
- Claude fallback при Grok грешка
- STM, LTM summaries, OpenAI embeddings
- facts extraction
- time-of-day prompt
- user image analysis чрез Grok Vision
- typing indicators + multi-bubble responses
- typing анимация за opening message
- soft-push text hint
- re-engagement (double-text)

### Частично подготвено, но не довършено

- автоматично изпращане на selfies/content
- paid content unlock flow
- content selection по tags
- реално използване на `sent_content` / `pending_unlocks`
- реално добавяне на image URLs към `ChatResponse.content_urls`

---

## 29. Практически извод

Sexting mode сега е по-прост и по-консистентен:

- **една** винаги-отворена persona вместо 3 stages
- **един** Gemini call за signals + класификация (по-евтино, по-бързо)
- **mood** слой за жива емоционална динамика без противоречия
- всичко генерира Grok; Claude е само резервен
- STM + LTM + facts памет
- реалистично chat pacing

Най-голямата липсваща част остава **реалното изпращане на content/images** от Victoria — архитектурата е подготвена, но pipeline-ът още не го прави.
