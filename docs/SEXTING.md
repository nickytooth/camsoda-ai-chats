# Sexting Mode — пълно обяснение на прост език

Този документ описва как работи **Sexting mode** в проекта — от момента, в който потребителят изпрати съобщение, до момента, в който Victoria върне отговор във frontend-а.

Целта е да е ясно:

- **какво влиза в backend-а**
- **как се избира persona**
- **кога е SFW и кога NSFW**
- **как работят intimacy нивата**
- **какво точно отива като system message към LLM-а**
- **как работи memory системата**
- **как се оформят отговорите като chat bubbles**
- **как работят снимките и content частта**
- **какво реално е имплементирано и какво само е подготвено**

---

## 1. Голямата картина

Sexting mode е основният chat режим, в който Victoria говори като реален човек в чат.

Той не работи като обикновен chatbot, който веднага отговаря на всяко съобщение. Вместо това backend-ът прави няколко неща:

1. Приема съобщението през WebSocket.
2. Ако потребителят е пратил снимка, анализира снимката с Grok Vision.
3. Записва съобщението в short-term memory.
4. Събира няколко бързи съобщения в batch.
5. След малко изчакване обработва всички натрупани съобщения заедно.
6. Класифицира дали съобщението е SFW или NSFW.
7. Оценява intimacy progression — колко напреднала е връзката.
8. Избира коя persona и кой model/provider да ползва.
9. Сглобява system prompt + memory + последни съобщения.
10. Изпраща prompt-а към LLM.
11. Записва отговора в базата.
12. Разделя отговора на отделни chat bubbles.
13. Изпраща ги през WebSocket с typing indicator и паузи.

На прост език: **Victoria не е само един prompt**. Отговорът й е резултат от persona + текущ stage + история + дългосрочна памет + facts + time-of-day context + SFW/NSFW routing.

---

## 2. Къде започва всичко

Основният вход за чата е WebSocket endpoint-ът:

```text
server/app.py
/ws/chat
```

Когато frontend-ът изпрати съобщение, backend-ът получава JSON с неща като:

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

и ги изпрати бързо едно след друго, backend-ът ги събира и ги обработва като един вход:

```text
hey
what are you doing
missed you
```

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

За всеки `user_id` има buffer:

```text
self._pending[user_id]
```

Всяко входящо sexting съобщение се добавя там.

Ако няма вече стартиран batch task, backend-ът стартира `_batch_collect()`.

`_batch_collect()`:

1. изчислява delay между `MIN_RESPONSE_DELAY` и `MAX_RESPONSE_DELAY`
2. умножава delay-а по time-of-day multiplier
3. ограничава delay-а до максимум 15 секунди
4. изчаква
5. взима всички pending съобщения
6. маха последователно повтарящи се еднакви съобщения
7. събира ги с нов ред
8. праща ги към `_process_sexting()`

---

## 4. Първо записване в memory

Още преди batch-ът да се обработи, user message се записва в базата:

```text
messages table
role = "user"
mode = "sexting"
```

Това става в:

```text
bot/memory/stm.py
add_message()
```

Причината е проста: ако user-ът refresh-не страницата, смени mode или WebSocket-ът падне, съобщението вече е запазено.

Това е short-term memory — STM.

---

## 5. Основният sexting pipeline

След batching-а се извиква:

```text
bot/chat_engine.py
_process_sexting()
```

Това е сърцето на sexting mode.

Там се случват следните неща:

1. Summarization/compaction на memory, ако е време.
2. Взимане на последните съобщения от STM.
3. Класификация SFW/NSFW.
4. Tracking на engagement.
5. Intimacy evaluation.
6. Избор на provider и persona.
7. LTM retrieval.
8. Soft-push hint, ако е време.
9. Взимане на user facts.
10. Build prompt.
11. Generate response.
12. Запис на assistant response.
13. Split на response-а на bubbles.

---

## 6. Двете persona-и

Има две persona YAML конфигурации:

```text
personas/victoria.yaml
personas/victoria_nsfw.yaml
```

### `victoria.yaml`

Това е основната/SFW persona.

Тя съдържа:

- identity
- възраст
- physical description
- voice
- scent
- background
- communication style
- linguistic markers
- pet names
- core memories
- opening lines
- stage instructions
- boundaries

Тази persona описва Victoria като:

- елегантна
- зряла
- контролирана
- sophisticated
- леко condescending
- забранена/опасна динамика
- short texting style
- без slang
- без emoji
- без chatbot тон

Това е основата на характера й.

### `victoria_nsfw.yaml`

Това е NSFW persona.

Тя не прави Victoria различен човек. Тя казва на модела:

> Когато нещата станат сексуални, Victoria не сменя характера си. Тя става по-интензивна версия на себе си.

Тоест:

- пак е елегантна
- пак е composed
- пак говори граматически правилно
- пак не звучи евтино или роботизирано
- пак държи контрол
- но вече може да говори по-директно и интимно

На прост език: **NSFW persona не заменя Victoria с друга личност. Тя отключва по-експлицитното поведение, но запазва нейния стил.**

---

## 7. Как се зареждат persona-ите

При startup на backend-а в `server/app.py` се случва:

```text
persona = load_persona()
nsfw_persona = load_persona(NSFW_PERSONA_FILE)
```

След това се създава `ChatEngine` с:

```text
persona = victoria.yaml
nsfw_persona = victoria_nsfw.yaml
sfw_provider = AnthropicProvider()
nsfw_provider = GrokProvider()
classifier_provider = GeminiProvider()
vision_provider = GrokProvider()
```

Тоест в паметта на приложението има:

- **SFW persona** — основният character profile
- **NSFW persona** — explicit/intimate variant
- **Claude/Anthropic** — за SFW отговори
- **Grok/xAI** — за NSFW отговори и story mode
- **Gemini** — за classification, summarization, intimacy scoring
- **OpenAI** — само за embeddings/memory search

---

## 8. Как се избира коя persona да се ползва

Това е много важно.

Изборът не е просто:

```text
ако съобщението е NSFW → NSFW persona
```

Реалното правило е:

```text
ако intimacy_stage >= 3 И classification == "nsfw":
    използвай nsfw_provider + nsfw_persona
иначе:
    използвай sfw_provider + sfw persona
```

Тоест има две условия:

1. Съобщението трябва да е класифицирано като NSFW.
2. User-ът трябва да е стигнал до intimacy stage 3.

Ако user-ът пише сексуално още в началото, но е stage 1, Victoria **няма да мине към NSFW persona**. Тя ще остане в SFW persona и ще deflect-не с класа.

Това е направено за slow-burn динамика.

---

## 9. SFW/NSFW classification

Класификацията става в:

```text
bot/router.py
classify()
```

Има два слоя.

### Fast keyword check

Първо backend-ът проверява дали текстът съдържа NSFW keywords.

Ако има match → директно връща:

```text
"nsfw"
```

Това е евтино и бързо, защото не вика LLM.

### Gemini fallback

Ако няма keyword match, backend-ът пита Gemini:

```text
Classify the following message as either SFW or NSFW.
Reply with exactly one word: SFW or NSFW.
```

Ако Gemini каже NSFW → classification е `nsfw`.

Иначе → `sfw`.

Ако Gemini fail-не → default е `sfw`.

---

## 10. Intimacy stages — как работят нивата

Sexting mode има 3 intimacy stage-а.

Те се пазят в SQLite таблицата:

```text
intimacy_state
```

с полета:

```text
user_id
stage
flirt_score
message_count
last_evaluated_at
```

Логиката е в:

```text
bot/intimacy.py
```

### Stage 1 — distant / curious

Това е началото.

Victoria е:

- заинтересована
- флиртува леко
- държи дистанция
- не е лесна
- не се хвърля директно в explicit talk
- ако user-ът натиска твърде рано, тя го спира елегантно

На прост език: **тя е intrigued, но user-ът още не е заслужил пълния достъп.**

### Stage 2 — warming up

Това е междинното ниво.

Victoria вече:

- е по-топла
- по-лична
- по-игрива
- може да говори suggestive
- може да използва double entendres
- може да признава attraction
- но още не минава към пълна explicit динамика

На прост език: **тя започва да се отваря, но все още контролира темпото.**

### Stage 3 — fully open

Това е отключеният режим.

Тук вече, ако съобщението е NSFW, backend-ът може да избере:

```text
nsfw_persona + Grok
```

Victoria вече:

- е напълно отворена
- може да бъде директна
- може да следва NSFW persona behavior
- но пак остава Victoria — елегантна, контролирана, sophisticated

На прост език: **това е моментът, в който NSFW persona реално може да влезе в употреба.**

---

## 11. Как се минава от stage 1 към stage 2 и 3

Всяко user съобщение се оценява от Gemini.

Gemini получава evaluation prompt, който казва:

- user-ът се опитва да съблазни sophisticated older woman
- тя цени charm, wit, respect и patience
- оцени съобщението по няколко категории

Категориите са:

```text
charm      - чар, комплименти, playful banter
respect    - уважение, правилен тон
humor      - хумор, cleverness
vulgarity  - грубост, вулгарност
pushing    - натискане на граници твърде рано
```

Gemini връща JSON със score за всяка категория.

Backend-ът събира числата:

```text
score_delta = charm + respect + humor + vulgarity + pushing
```

После:

```text
new_score = max(0, old_score + score_delta)
message_count += 1
```

### Thresholds

В кода thresholds са:

```text
Stage 2:
- поне 15 съобщения
- поне 30 flirt score

Stage 3:
- поне 30 съобщения
- поне 70 flirt score
```

Тоест user-ът не може да стигне stage 3 само с едно добро съобщение.

Трябва:

- достатъчно conversation history
- достатъчно добър cumulative flirt score

### Може ли stage да пада назад

Не.

Кодът казва, че stage никога не се връща назад.

Ако user стигне stage 2, остава поне stage 2.

Ако стигне stage 3, остава stage 3.

Score може да не расте, но stage не пада.

---

## 12. Как personality-то й реално се сменя

Personality-то не се сменя с един switch. То се оформя от няколко слоя.

### Layer 1 — базова persona

Това винаги е character identity:

- коя е Victoria
- как говори
- каква е историята й
- каква е динамиката
- какви pet names използва
- какви са hard rules

### Layer 2 — stage instructions

В sexting mode към system prompt-а се добавя stage-specific инструкция:

```text
=== INTIMACY STAGE 1/3 ===
...
```

или:

```text
=== INTIMACY STAGE 2/3 ===
...
```

или:

```text
=== INTIMACY STAGE 3/3 ===
...
```

Това казва на LLM-а каква е текущата динамика.

Точно тук се оформя дали Victoria е:

- дистанцирана
- warming up
- fully open

### Layer 3 — SFW vs NSFW persona

При stage 1 и 2 винаги се ползва SFW persona.

При stage 3 + NSFW classification се ползва NSFW persona.

Това променя system prompt-а драстично, защото `persona.to_system_prompt()` вече се строи от друг YAML файл.

### Layer 4 — memory

Ако Victoria знае, че user-ът харесва определен tone, pet name или динамика, това може да бъде inject-нато като facts или LTM memory.

Това персонализира отговора.

### Layer 5 — time context

Ако е morning/evening/night в Miami, prompt-ът добавя контекст какво прави тя и каква е енергията й.

Така тя може да звучи по-различно според времето.

### Layer 6 — последните съобщения

STM дава директен conversational context.

Ако последните 10-20 съобщения са playful, тя продължава playful.

Ако са serious, тя може да отговори serious.

---

## 13. Какво точно отива като system message

System message се строи в:

```text
bot/prompt_builder.py
build_prompt()
```

На LLM-а се праща list от messages:

```python
[
  {"role": "system", "content": system_text},
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  ...
]
```

`system_text` е сглобен от няколко секции.

### 1. Persona system prompt

Първо влиза:

```text
persona.to_system_prompt()
```

Това включва:

- identity: име, възраст, tagline
- physical appearance
- voice
- scent
- communication style
- linguistic markers
- pet names
- background
- core memories
- boundaries / hard rules

Това е най-важната част от character-а.

### 2. User name

Ако има user name, се добавя:

```text
The user's name is X. Use it naturally...
```

Името може да дойде от:

- WebSocket query param `user_name`
- facts memory, ако е извлечено от conversation

### 3. Time-of-day context

Добавя се секция от `get_time_prompt()`.

Примерно казва:

```text
RIGHT NOW: It's Monday, June 15, 5:30 PM in Miami.
You're home from work, pouring a glass of wine...
Your energy: high...
Don't announce this unless it comes up naturally.
```

Ако има `OPENWEATHER_API_KEY`, може да добави и weather в Miami.

### 4. Texting style instructions

За sexting mode винаги се добавя:

```text
TEXTING STYLE — THIS IS A REAL CHAT, NOT AN ESSAY
```

Там са правилата:

- да пише като реален човек на телефона
- да не завършва с period
- question marks и ellipses са OK
- short/punchy lines
- 1-3 messages, each on its own line
- no slang като `u`, `lol`
- emojis рядко

Това е причината отговорите да изглеждат като chat, не като essay.

### 5. Intimacy stage instructions

Добавя се:

```text
=== INTIMACY STAGE X/3 ===
...
```

Това идва от persona YAML.

При stage 1 казва да е distant/interested и да deflect-ва твърде ранна explicit ескалация.

При stage 2 казва да се затопля, да е suggestive, но още не fully explicit.

При stage 3 казва, че е fully open.

### 6. Known facts

Ако има facts за user-а, се добавя:

```text
Known facts about this person (use naturally, don't recite):
- name: ...
- location: ...
- kinks: ...
- favorite_color: ...
```

Това са структурирани facts от `user_facts` таблицата.

### 7. Long-term memories

Ако LTM retrieval върне релевантни memories, се добавя:

```text
What you remember about this person:
- ...
- ...
```

Ако няма memories, се добавя:

```text
You don't know anything about this person yet. Get to know them naturally.
```

### 8. Soft-push hint

Ако engagement системата реши, че е време, добавя:

```text
IMPORTANT FOR THIS REPLY: Naturally hint that you have private photos...
```

Важно: това е само hint в prompt-а. Не изпраща реална снимка автоматично.

---

## 14. Какво НЕ е system message

Последните user/assistant съобщения не са system message.

Те се добавят след system message-а като нормални chat messages:

```python
{"role": "user", "content": "..."}
{"role": "assistant", "content": "..."}
```

Това е conversation history от STM.

---

## 15. Memory системата

Memory системата има няколко слоя.

### STM — short-term memory

STM е таблицата:

```text
messages
```

Там се пазят всички chat messages:

```text
id
user_id
role
content
timestamp
mode
```

`mode` е важно, защото `sexting` и `story` имат отделна видима история.

За sexting prompt-а backend-ът взима последните `STM_MAX_TURNS` turn-а.

В config стойността е:

```text
STM_MAX_TURNS = 18
```

Функцията е:

```text
get_recent_messages(user_id, STM_MAX_TURNS, mode="sexting")
```

Това дава последния контекст, за да не забравя какво си казали преди малко.

### LTM — long-term memory

LTM е таблицата:

```text
memories
```

Там се пазят обобщени неща:

```text
category
content
importance
embedding
created_at
last_accessed
```

Примери за категории:

```text
fact
preference
relationship
event
thread
```

LTM не пази целия разговор дума по дума. То пази summary/memory entries.

### Facts — структурирани факти

Facts са в таблицата:

```text
user_facts
```

Примери:

```text
name: Alex
location: London
job: designer
kinks: likes being called ...
boundaries: ...
```

Facts са по-детерминистични от LTM.

Тоест ако има fact `name`, той се inject-ва почти винаги и Victoria трябва да го използва естествено.

---

## 16. Как STM става LTM

При всяко `_process_sexting()` се проверява:

```text
maybe_summarize(user_id, _llm_call)
```

Тази функция гледа общия брой user turns across modes.

Ако user turns са поне:

```text
STM_MAX_TURNS = 18
```

тогава взима най-старите:

```text
STM_SUMMARIZE_BATCH = 10
```

и ги праща към Gemini за summarization.

Gemini трябва да върне JSON с:

```json
{
  "memories": [...],
  "facts": [...]
}
```

После backend-ът:

1. Прави embeddings на memory текстовете с OpenAI.
2. Проверява дали има сходна стара memory.
3. Ако има — update-ва я.
4. Ако няма — създава нова.
5. Upsert-ва facts в `user_facts`.
6. Изтрива старите raw messages, които са summary-знати.

На прост език: **старите chat messages се компресират в memories и facts, за да не расте prompt-ът безкрайно.**

---

## 17. Как LTM retrieval решава кога да търси memory

Не всяко съобщение прави vector search, защото това струва API call към OpenAI embeddings.

Функцията е:

```text
should_retrieve(user_id, message)
```

Тя връща `true`, ако:

- user-ът казва нещо като `remember`, `you said`, `last time`, `earlier`
- съобщението е по-дълго от 30 символа
- минал е голям gap от последното съобщение
- всеки N-ти turn като fallback

Ако е просто:

```text
hey
ok
yeah
```

обикновено няма retrieval.

---

## 18. Как се избира кои memories да влязат в prompt-а

Ако retrieval се активира:

1. Прави embedding на текущото user съобщение.
2. Взима всички memories от DB.
3. Сравнява query embedding срещу memory embeddings.
4. Смята score:

```text
similarity * 0.5
+ importance * 0.3
+ recency * 0.2
```

Тоест memory е по-вероятно да бъде избрана, ако:

- е семантично близка до текущото съобщение
- е важна
- е сравнително скорошна

В prompt-а влизат top K memories.

В config:

```text
LTM_TOP_K = 5
```

---

## 19. Engagement system

Engagement системата е отделна от intimacy системата.

Тя се пази в:

```text
engagement_state
```

с полета:

```text
nsfw_count
total_messages
last_push_at
last_selfie_at
last_message_at
last_reengage_at
```

При всяко user съобщение:

```text
track_message(user_id, classification)
```

увеличава:

- `total_messages`
- `nsfw_count`, ако classification е `nsfw`

### Soft push

Ако `nsfw_count >= SOFT_PUSH_THRESHOLD`, backend-ът може да inject-не soft-push hint в prompt-а.

Threshold в кода:

```text
SOFT_PUSH_THRESHOLD = 8
```

Hint-ът казва на Victoria да намекне естествено, че има private photos.

Важно: **това не праща снимка. Само казва на LLM-а да намекне.**

След soft push, `nsfw_count` се reset-ва на 0.

---

## 20. Снимки от потребителя

User може да прати снимка през WebSocket като base64.

Backend-ът я decode-ва:

```text
image_bytes = base64.b64decode(data["image"])
```

После в `process_sexting_batched()`:

```text
vision_provider.analyze_image(image_bytes)
```

`vision_provider` е GrokProvider.

Grok Vision получава prompt:

```text
Describe what you see in this image in 1-2 sentences.
Be specific about content, setting, people visible.
If it contains nudity or sexual content, describe it plainly.
Return only the description.
```

Резултатът се добавя към user text като:

```text
[User sent a photo: description]
```

Тоест LLM-ът не вижда директно снимката в основния chat prompt. Той вижда **текстово описание на снимката**.

На прост език: **снимката се превръща в описание, после Victoria отговаря на описанието.**

---

## 21. Снимки/content от Victoria

В проекта има подготовка за content система:

- `CONTENT_DIR`
- `/content` static serving
- `sent_content` таблица
- `pending_unlocks` таблица
- `ChatResponse.content_urls`
- `should_send_selfie()` в `engagement.py`

Но в текущия sexting pipeline има важен факт:

**Victoria реално не избира и не изпраща снимки автоматично.**

Причината е, че:

- `should_send_selfie()` съществува, но не се извиква в `_process_sexting()`
- `content_urls` съществува в `ChatResponse`, но `_process_sexting()` връща само `messages`
- няма активен модул, който избира файл от `content/` и го добавя към `content_urls`

Тоест в момента content системата е **частично подготвена**, но не е вързана към реалния chat flow.

Какво работи:

- backend може да serve-ва файлове от `/content`, ако папката съществува
- response sender може да изпрати image event, ако `content_urls` има нещо
- DB schema има таблици за sent/pending content

Какво липсва:

- content picker
- tagging/selection logic
- logic кога да се прати free selfie
- logic кога да се предложи платено unlock-ване
- реално добавяне на URL към `ChatResponse.content_urls`

На прост език: **Victoria може да говори за снимки, но кодът още не й дава реална снимка за изпращане.**

---

## 22. Как се генерира отговорът

След като provider и persona са избрани, backend-ът прави:

```text
prompt_messages = build_prompt(...)
response_text = await provider.generate(prompt_messages)
```

Ако primary provider fail-не, backend-ът пробва fallback:

- ако Claude fail-не → пробва Grok
- ако Grok fail-не → пробва Claude

Ако и fallback fail-не → връща:

```text
...
```

Ако response е празен → връща празен `ChatResponse`.

Ако има response → записва го в STM като:

```text
role = "assistant"
mode = "sexting"
```

Важно: в DB се пази **целият response text**, преди да бъде разделен на bubbles.

---

## 23. Как се оформят отговорите като chat bubbles

LLM-ът е инструктиран да връща 1-3 кратки реда, разделени с newline.

Примерно:

```text
Well, look at you
Starting bold tonight
I should probably be more responsible than this
```

Backend-ът извиква:

```text
_split_response(response_text)
```

Това прави:

1. заменя long dashes с normal dash
2. split-ва по `\n`
3. маха празните редове
4. връща list от strings

Всеки string става отделен message bubble.

---

## 24. Typing indicator и delays

След като response е split-нат, `server/app.py` изпраща всяко bubble отделно.

За всяко bubble:

1. праща `typing_start`
2. чака random delay според дължината
3. праща `typing_end`
4. праща `message`
5. ако има следващо bubble, чака още 0.5-1.5 секунди

Delay според дължина:

```text
< 50 chars   → 1.0 - 2.5 sec
< 150 chars  → 2.0 - 4.0 sec
>= 150 chars → 3.0 - 6.0 sec
```

Това е отделно от batch delay-а.

Има два вида забавяне:

1. **batch collect delay** — преди LLM processing, докато събира user messages
2. **typing delay** — след LLM response, докато праща bubbles

---

## 25. Time-of-day система

Victoria има time context според Miami timezone.

Файл:

```text
bot/time_context.py
```

Периоди:

```text
early_morning
morning
afternoon
evening
night
late_night
```

Всеки период има:

- mood
- activity
- energy
- preferred_tags
- delay_multiplier

Това влияе на две неща:

### Prompt-а

В system message влиза какво прави Victoria сега.

Например вечер може да е вкъщи, да пие wine, да unwind-ва.

### Response delay

Batch delay-ът се умножава по `delay_multiplier`.

Например:

- early morning → по-бавно
- night → по-бързо
- afternoon/evening → нормално

---

## 26. Базата данни — кои таблици участват

SQLite базата е:

```text
data/bot.db
```

Основни таблици за sexting:

### `messages`

Пази raw chat history.

Използва се за STM и history endpoint.

### `memories`

Пази long-term memories с embeddings.

Използва се за LTM retrieval.

### `user_facts`

Пази структурирани facts за user-а.

Те се inject-ват в prompt-а.

### `engagement_state`

Пази counters за engagement и soft push.

### `intimacy_state`

Пази stage, flirt score и message count.

### `sent_content`

Подготвена таблица за tracking на изпратен content.

В момента не е вързана към активен content sending flow.

### `pending_unlocks`

Подготвена таблица за paid/unlockable content.

В момента не е вързана към активен purchase/unlock flow.

---

## 27. Кои модели се ползват за какво

### Anthropic Claude

Използва се като SFW provider.

Тоест ако:

- stage е 1 или 2
- или classification е SFW

тогава обикновено се ползва Claude.

### xAI Grok

Използва се за:

- NSFW provider
- Story mode provider
- Vision analysis на user снимки

В sexting mode Grok се ползва за text response само когато:

```text
intimacy_stage >= 3
AND
classification == "nsfw"
```

### Google Gemini

Използва се за:

- SFW/NSFW classification fallback
- intimacy scoring
- STM summarization към LTM
- memory compaction

### OpenAI

Използва се само за embeddings:

- embed current user message
- embed memory entries
- cosine similarity search

---

## 28. Какво става при първо отваряне на sexting mode

Когато frontend-ът поиска history:

```text
GET /api/history/sexting
```

ако няма messages, backend-ът seed-ва opening message от persona:

```text
engine.persona.get_random_opening()
```

Opening line идва от `victoria.yaml` → `opening_lines`.

Ако opening text има няколко реда, всеки ред се записва като отделно assistant message.

Така chat-ът не започва празен — Victoria започва разговора.

---

## 29. Какво става при reset

Endpoint:

```text
POST /api/reset
```

Трие user data от:

```text
messages
memories
user_facts
sent_content
story_progress
engagement_state
intimacy_state
```

Това връща user-а в чисто състояние.

След reset:

- stage пак е 1
- flirt_score е 0
- memories ги няма
- facts ги няма
- history я няма
- opening message може пак да се seed-не при history call

---

## 30. Най-важното за persona влиянието

Persona влияе най-силно чрез system message.

LLM-ът не знае коя е Victoria сам по себе си. Той разбира това от system prompt-а, който backend-ът му подава.

В system prompt-а влизат:

```text
1. коя е Victoria
2. как изглежда
3. как звучи
4. как пише
5. каква е историята й
6. какви са правилата й
7. какви pet names използва
8. какво никога не трябва да прави
9. текущ intimacy stage
10. текущ time-of-day context
11. user facts
12. retrieved memories
13. optional soft-push hint
```

Това оформя отговора.

Ако stage е 1, system prompt-ът казва: дръж дистанция, deflect-вай ранна ескалация.

Ако stage е 2, казва: warming up, suggestive, more personal.

Ако stage е 3 и input е NSFW, се сменя persona YAML към `victoria_nsfw.yaml`, което позволява по-интимен стил, но пак в характера на Victoria.

---

## 31. Накратко — целият pipeline в едно

```text
Frontend sends WebSocket message
        ↓
server/app.py receives it
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
wait 3-10 sec * time multiplier, max 15 sec
        ↓
combine pending messages
        ↓
_process_sexting()
        ↓
maybe summarize old STM → LTM/facts
        ↓
get recent STM messages
        ↓
classify SFW/NSFW
        ↓
track engagement
        ↓
evaluate intimacy stage with Gemini
        ↓
choose persona + provider
        ↓
maybe retrieve LTM memories
        ↓
maybe add soft-push hint
        ↓
get user facts
        ↓
build system message
        ↓
append recent conversation messages
        ↓
call Claude or Grok
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

## 32. Current implementation status

### Работи в момента

- WebSocket chat
- Sexting batching
- SFW/NSFW classification
- SFW provider routing
- NSFW provider routing след stage 3
- SFW persona
- NSFW persona
- 3-stage intimacy progression
- Gemini scoring
- STM
- LTM summaries
- OpenAI embeddings
- facts extraction
- time-of-day prompt
- user image analysis чрез Grok Vision
- typing indicators
- multi-bubble responses
- soft-push text hint

### Частично подготвено, но не довършено

- автоматично изпращане на selfies/content
- paid content unlock flow
- content selection по tags
- реално използване на `sent_content`
- реално използване на `pending_unlocks`
- реално добавяне на image URLs към `ChatResponse.content_urls`

---

## 33. Ако искаме да развием Sexting mode нататък

Най-логичните следващи подобрения са:

1. Да се добави content picker, който избира снимка от `content/` по tags.
2. Да се извика `should_send_selfie()` в `_process_sexting()`.
3. Да се добавя избран image URL в `ChatResponse.content_urls`.
4. Да се записва изпратеният content в `sent_content`.
5. Да се направи paid unlock логика през `pending_unlocks`.
6. Да се добави content config файл с категории, tags и prices.
7. Да се добави admin/dev endpoint за debugging на current stage, score, facts и memories.

---

## 34. Практически извод

Sexting mode в момента е добре структуриран като conversational engine:

- има character system
- има slow-burn progression
- има routing между SFW и NSFW модели
- има short-term и long-term memory
- има user facts
- има image understanding за user uploads
- има реалистично chat pacing

Най-голямата липсваща част е **реалното изпращане на Victoria content/images**. Архитектурата е подготвена за това, но pipeline-ът още не го прави.
