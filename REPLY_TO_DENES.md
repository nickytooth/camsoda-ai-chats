Hey Denes,

Thanks again for taking the time to go through everything so thoroughly - really appreciate the quality of your feedback. It made prioritizing super easy.

I went ahead and implemented the quick wins based on your suggestions:

1. Reply/quote context - She now reads reply_to_message from the Telegram update. Quoted messages get injected with relative time ("~2 hours ago", "yesterday") exactly as you suggested. If the quoted text is still in the STM window it skips the annotation since the context is already there.

2. Math deflection - Two layers now. Persona rule in both YAML files (she's terrible at math, always deflects or guesses wrong). Plus a regex backstop that detects digits + operators and injects a hard-deflect hint into the prompt, so even if the soft rule gets overridden, the backstop catches it.

3. Per-bubble pacing - Replaced the flat 0.5-1.5s inter-bubble delay with length-scaled timing: 2-4s for short messages, 3-6s for medium, 5-9s for longer ones. Typing indicator re-fires before each bubble.

4. Read receipts - After the read delay, she now calls read_chat_history() to mark messages as read (blue ticks), then waits a 1-2.5s beat before the typing indicator starts. Sequence: wait -> blue ticks -> pause -> typing -> send.

5. Telegram name - She grabs first_name from the update metadata on first contact and injects it into the system prompt every turn. No more asking for names Telegram already provides.

6. Media logging - STM entries now include filename, tag, tier, and caption. So she can reference specifics ("the mirror pic from earlier") instead of just knowing she sent "a selfie".

7. Debounce floods - Identical consecutive messages in the buffer get collapsed before hitting the LLM. Saves tokens without losing info.

The bigger stuff - LTM retrieval gating, structured fact store, and the teaser content re-tagging - I'm planning to tackle over the weekend. Those need a bit more thought to get right, especially the fact store schema.

I'll put it back online on Sunday - feel free to poke at it again after that.

Cheers,
Nicky
