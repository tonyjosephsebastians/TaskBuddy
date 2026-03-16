# TaskBuddy Demo Script

## Slide 1 - Title and summary

TaskBuddy is a locally runnable FastAPI application with a React interface, deterministic tool routing, persistent chat threads, and an execution trace for every saved task. This five-minute walkthrough covers the product from both business and technical angles. I will show how a user accesses the app, how supported prompts are handled, how the architecture is organized, and how the supporting documentation pack helps explain the build.

## Slide 2 - What TaskBuddy does

At the user level, TaskBuddy behaves like a focused productivity workspace. A signed-in user creates a chat, enters a supported prompt, and receives a response card that shows the final output first, followed by the tool used, structured output, and a trace of the execution steps. That flow matters because it makes the app easy to understand for a business audience while still exposing enough detail for technical validation and manual testing.

## Slide 3 - Roles and protected access

The app has two roles: admin and user. The bootstrap admin can run tasks like any other user, but can also open the admin page to create or delete local accounts. Standard users can sign in, run supported tasks, and review their own thread history only. Authentication is cookie-based, thread APIs are protected, and the admin endpoints are restricted to the admin role, which keeps the local setup lightweight while still enforcing access boundaries.

## Slide 4 - End-user workflow

The fastest way to demo the product is to start at the login screen, sign in as admin, create a new chat, and submit a simple text-processing request such as converting quoted text to uppercase. After that, switch to a multi-tool request so the audience can see the numbered final output and the two-step trace. This slide is where I call out the response-card order, the saved-thread history, and the fact that the active chat automatically scrolls to new output.

## Slide 5 - Tool catalog and sample prompts

TaskBuddy currently supports five tool families. Text processing handles case transforms and word or character counts. The calculator handles arithmetic expressions with natural-language operator phrases. The weather tool returns deterministic mock data for supported cities. The currency converter uses fixed rates for a small supported currency set. The transaction categorizer maps merchant descriptions to categories. The documentation pack includes sample prompts and manual tests so each tool can be validated quickly and consistently.

## Slide 6 - Access and run options

For normal app usage, the project exposes one-command startup scripts for Windows and for Linux, macOS, WSL, or Git Bash. Docker and Docker Compose are also documented. For documentation generation, the setup is now intentionally isolated: the app runtime keeps its own requirements in `.venv`, while the documentation pack uses `.review-pack-venv` and `requirements-review-pack.txt`. That means presentation, DOCX, Playwright, and video dependencies never pollute the app runtime environment.

## Slide 7 - Architecture and LangGraph orchestration

From a technical perspective, FastAPI serves both the REST and SSE APIs and the built frontend. The route layer hands task execution to the `AgentController`, which stays stable as the API-facing facade. Under that layer, LangGraph manages the orchestration stages: validation, planning, tool execution, retry handling, and response assembly. The actual tool selection remains deterministic through the interpreter, which means the graph improves structure and traceability without turning the app into a black-box model planner.

## Slide 8 - Folder structure, key files, and APIs

This slide ties the codebase back to the documentation. The `backend/` folder contains the FastAPI app, route definitions, persistence layer, safety checks, orchestration, and tool implementations. The `frontend/` folder contains the React app, API client, types, and tests. `docs/` holds the user guide, technical documentation, manual test plan, and demo script sources. `scripts/` holds the app launchers, report exporter, and documentation-pack generator. The technical document also lists the major endpoints and explains what each API exists to do.

## Slide 9 - Testing evidence and outputs

TaskBuddy includes automated backend and frontend coverage, plus exported evidence for review. Backend tests exercise the interpreter, controller, repository, tools, and API behavior. Frontend tests cover login, routing, thread limits, task-flow limits, auto-scroll, and admin interactions. JUnit XML outputs feed an HTML dashboard and an Excel summary, and the manual test plan adds tool-by-tool checks for local validation. Together, those assets make the product easier to assess from both correctness and presentation standpoints.

## Slide 10 - Limits and next improvements

The last slide closes with current limits and realistic next steps. The tool set is intentionally challenge-scoped, weather and currency data are mock-based, and routing remains deterministic for explainability. With more time, the biggest improvement area would be model refinement and richer semantic routing while preserving trace clarity. Other next steps include more end-to-end browser automation, deeper component modularization on the frontend, and continued improvement of the documentation pack and narrated demo workflow.
