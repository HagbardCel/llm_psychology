# Therapy style selection not working

## Issue

The therapy style selection should work by the user entering the number of his preferred style in the console-ui and the ui sending the respective signal to the backend. Instead the ui is currently asking the user to post a value to the backend, which does not make any sense. 

## Example

============================================================

============================================================
🎯 ASSESSMENT RECOMMENDATIONS
============================================================
1. cbt (score: 0.85)
   This patient appears to be a strong candidate for CBT. They clearly articulate specific problems (low self-esteem, social anxiety, procrastination, anger) and are interested in understanding how these manifest. The patient's willingness to discuss triggers and internal experiences related to social anxiety suggests an openness to exploring the thought-feeling-behavior connection. While past experiences are touched upon, the focus remains on current difficulties and their impact, aligning with CBT's present-oriented approach. The patient's description of their relationships and challenges in maintaining friendships also indicates a desire for practical strategies to improve social functioning, a core component of CBT.
---
2. freud (score: 0.85)
   This patient appears to be a strong candidate for Freudian analysis. They express curiosity about the roots of their low self-esteem and its manifestations, indicating a desire for deeper understanding. The patient readily shares significant early childhood experiences, including parental tension, father's anger, sibling envy, and the impact of academic success, all of which are fertile ground for psychoanalytic exploration. Their willingness to discuss complex relational dynamics and a reflective communication style further support suitability for long-term, in-depth therapy.
---
3. jung (score: 0.70)
   This patient presents with several indicators that suggest they could benefit from Jungian analysis. Their description of feeling like a 'robot' and 'not being myself' points to a disconnection from their true self, a key area Jungian therapy addresses. The patient's mention of deriving value from being the 'smartest kid' and the subsequent bullying suggests an interest in understanding the complex interplay of external validation and internal self-worth. While not explicitly mentioning dreams or symbols, the introspective nature of their responses and the exploration of childhood dynamics indicate a capacity for depth-oriented exploration.
---
To select a style, submit POST /api/workflow/select_therapy_style with the desired selected_therapy_style value.


Your response: 3
USER: 3

THERAPIST: Thank you for letting me know. It seems there's a technical issue preventing me from accessing the specific details of your therapy plan and our ongoing conversation. I understand that this is frustrating and I sincerely apologize for any inconvenience this causes.

Since I cannot access your plan or the full context of our previous interaction, I am unable to proceed with the session as intended.

**I recommend that you contact the support team for the platform or service you are using.** They should be able to help diagnose and resolve this technical problem so that we can resume our session effectively.

Please let me know if there's anything else I can do from my end once the technical issue is resolved.
============================================================
🎯 ASSESSMENT RECOMMENDATIONS
============================================================
1. cbt (score: 0.85)
   This patient appears to be a strong candidate for CBT. They clearly articulate specific problems (low self-esteem, social anxiety, procrastination, anger) and are interested in understanding how these manifest. The patient [...]