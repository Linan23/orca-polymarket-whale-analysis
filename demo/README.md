# Local Demonstration

The local React/FastAPI dashboard is the project's demonstration layer. It presents validated artifacts produced by the analytical pipeline; it is not a separate source of model results.

## Demonstration Flow

1. State the research question and explain why prediction-market whale activity matters.
2. Show how reliability combines volume, profitability, consistency, and prior history.
3. Inspect an influential trader whose activity precedes later market movement.
4. Show a market's whale-pressure timeline and 12-hour/24-hour prediction.
5. Compare the price/no-change benchmark, linear baseline, Random Forest, and LightGBM.
6. Show uncertainty, category performance, failure cases, and limitations.
7. Conclude whether whale activity adds useful predictive information.

Anthony, Noah, and Uday should receive approximately equal speaking time. The demonstration must label findings as predictive associations and must remain useful if the final result is weak or inconclusive.

## Local Start

Follow `docs/SETUP_LOCAL.md`, then start the API and frontend using the documented commands. Before the final demonstration, run `scripts/verify_repository.sh` from a clean checkout.
