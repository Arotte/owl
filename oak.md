# Richard Sutton's OaK (Options and Knowledge) Architecture

OaK is a conceptual framework for building superintelligent agents through continual, experience-driven learning. It was introduced by Richard Sutton — Turing Award winner and "father of reinforcement learning" — at RLC 2025 and later at NeurIPS 2025. The name stands for **O**ptions (reusable behavioral policies) and **K**nowledge (understanding of how the world changes when those options are executed).

## Three foundational principles

1. **General-purpose**: The agent starts with no task-specific knowledge about its environment.
2. **Experience-driven**: All knowledge is acquired through direct interaction — observing, acting, and receiving rewards at runtime. Nothing is programmed in at design time.
3. **Reward hypothesis**: All goals reduce to maximizing a scalar reward signal.

## Three special features

1. **Continual learning** — All components learn continuously throughout the agent's lifetime, avoiding catastrophic forgetting. There is no separate "training phase" vs. "deployment phase."
2. **Meta-learned step sizes** — Each learnable weight has its own step-size parameter, optimized through online cross-validation, so the agent meta-learns *how* to generalize.
3. **FC-STOMP progression** — A five-step hierarchy for building increasingly abstract representations:
   - **F**eature Construction
   - **S**ubTask posing
   - **O**ption learning
   - **M**odel learning
   - **P**lanning

   This loop is self-reinforcing: features that help with planning become the basis for the next, more abstract layer of knowledge.

## Sutton's critique of the current AI industry

OaK is motivated by Sutton's argument that the AI industry "has lost its way" by scaling LLMs that memorize static data rather than building agents that learn by doing. He sees current systems as having two critical flaws:

- Knowledge is baked in at design time, not discovered through learning.
- They suffer from catastrophic forgetting and cannot learn continually.

He ties this back to his famous **"Bitter Lesson"**: scalable, general-purpose methods always win over hand-crafted human knowledge in the long run.

## Current status

OaK is a **vision and architectural blueprint**, not a fully implemented system. Sutton acknowledges the key missing piece is reliable, stable deep continual learning — algorithms that can keep learning indefinitely without forgetting. He positions OaK as the path forward once that problem is solved, with open-ended complexity limited only by available compute.
