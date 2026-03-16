# TaskBuddy Manual Test Plan

## Objective

Validate that TaskBuddy routes supported prompts to the correct tool, returns the expected result shape, and enforces the documented limits and validation rules.

## Environment prerequisites

| Item | Value |
| --- | --- |
| App URL | `http://localhost:8000` |
| Required runtime | FastAPI app running locally or through Docker Compose |
| Browser | Latest Chrome, Edge, or Firefox |
| Default admin account | `admin` / `admin123` |
| Recommended test data | Fresh local database or a dedicated temporary environment |

## Tester setup

1. Start TaskBuddy locally or with Docker Compose.
2. Sign in as `admin`.
3. Keep the browser developer console open if you want to watch SSE activity.
4. Start a fresh chat unless the case explicitly requires an existing thread.
5. Record the actual output, tools used, and trace observations.

## Expected user accounts

| Account | Purpose |
| --- | --- |
| `admin` | Run all tool tests and access the admin page |
| optional `user` account | Confirm non-admin access boundaries when needed |

## Result recording template

| Field | Value to capture |
| --- | --- |
| Tester name |  |
| Date |  |
| Build / commit |  |
| Case ID |  |
| Actual output |  |
| Tools used |  |
| Trace observations |  |
| Status | Pass / Fail / Blocked |
| Notes |  |

## TextProcessorTool cases

| Case ID | Sample input | Expected tool | Expected final output pattern | Trace/tool notes |
| --- | --- | --- | --- | --- |
| TXT-01 | `Convert "task buddy" to uppercase` | `TextProcessorTool` | `TASK BUDDY` | One tool only. |
| TXT-02 | `Make "TASK BUDDY" lowercase` | `TextProcessorTool` | `task buddy` | One tool only. |
| TXT-03 | `Title case "task buddy review pack"` | `TextProcessorTool` | `Task Buddy Review Pack` | One tool only. |
| TXT-04 | `Count the word "test"` | `TextProcessorTool` | `1` | Output data shows `word_count`. |
| TXT-05 | `Count characters in "task buddy"` | `TextProcessorTool` | Numeric count | Output data shows `char_count`. |
| TXT-06 | `Convert "task buddy and test bussy and file buddy" to uppercase` | `TextProcessorTool` | Uppercased full quoted string | Must not be blocked as fake multi-subtask input. |

## CalculatorTool cases

| Case ID | Sample input | Expected tool | Expected final output pattern | Trace/tool notes |
| --- | --- | --- | --- | --- |
| CALC-01 | `Add 3+2` | `CalculatorTool` | `5.0` | One calculator step. |
| CALC-02 | `What is (3 + 4) * 2?` | `CalculatorTool` | `14.0` | Parentheses respected. |
| CALC-03 | `What is 8 minus 3?` | `CalculatorTool` | `5.0` | Natural-language operator mapping. |
| CALC-04 | `Multiply 6 by 7` | `CalculatorTool` | `42.0` | Natural-language multiplication mapping. |
| CALC-05 | `Difference between 20 and 6` | `CalculatorTool` | `14.0` | `and` must stay inside one calculator request. |
| CALC-06 | `Calculate 10 / 0` | `CalculatorTool` | Handled failure or validation message | Must not crash the app. |

## WeatherMockTool cases

| Case ID | Sample input | Expected tool | Expected final output pattern | Trace/tool notes |
| --- | --- | --- | --- | --- |
| WTH-01 | `What is the weather in Toronto?` | `WeatherMockTool` | `Toronto: Cloudy, 8C, humidity 71%.` | Supported city. |
| WTH-02 | `Forecast for London` | `WeatherMockTool` | Includes `London` and mock condition | Supported city via synonym. |
| WTH-03 | `Temperature in New York` | `WeatherMockTool` | Includes `New York` temperature | Supported city via temperature wording. |
| WTH-04 | `Humidity in Chicago` | `WeatherMockTool` | Includes `Chicago` humidity | Supported city via humidity wording. |
| WTH-05 | `Condition in Sydney` | `WeatherMockTool` | Includes `Sydney` condition | Supported city via condition wording. |
| WTH-06 | `Weather in Paris` | `WeatherMockTool` | Handled validation or unsupported city message | Unsupported city must not return data for another city. |

## CurrencyConverterTool cases

| Case ID | Sample input | Expected tool | Expected final output pattern | Trace/tool notes |
| --- | --- | --- | --- | --- |
| CUR-01 | `Convert 100 CAD to USD` | `CurrencyConverterTool` | `100.00 CAD = ... USD` | Supported conversion. |
| CUR-02 | `Exchange 15 USD to CAD` | `CurrencyConverterTool` | `15.00 USD = ... CAD` | Natural-language synonym. |
| CUR-03 | `Convert 67 CAD` | `CurrencyConverterTool` | `67.00 CAD = 67.00 CAD` | Same-currency fallback only when no target is supplied. |
| CUR-04 | `Convert 67 CAD to INR` | `CurrencyConverterTool` | Handled failure for unsupported currency | Error code should be `CURRENCY_NOT_SUPPORTED`. |
| CUR-05 | `Convert 20 GBP to AUD` | `CurrencyConverterTool` | `20.00 GBP = ... AUD` | Supported fixed-rate conversion. |
| CUR-06 | `Convert -10 USD to CAD` | `CurrencyConverterTool` | Handled validation failure | Negative amounts must be rejected. |

## TransactionCategorizerTool cases

| Case ID | Sample input | Expected tool | Expected final output pattern | Trace/tool notes |
| --- | --- | --- | --- | --- |
| TRX-01 | `Categorize Starbucks transaction` | `TransactionCategorizerTool` | `Category: dining` | No currency conversion should run. |
| TRX-02 | `Categorize Starbucks transaction 45 CAD` | `TransactionCategorizerTool` | `Category: dining` | Amount may appear in output data. |
| TRX-03 | `Classify Costco spend` | `TransactionCategorizerTool` | `Category: groceries` | Keyword-based mapping. |
| TRX-04 | `Categorize Shell transaction` | `TransactionCategorizerTool` | `Category: transport` | Keyword-based mapping. |
| TRX-05 | `Categorize Airbnb transaction` | `TransactionCategorizerTool` | `Category: travel` | Keyword-based mapping. |
| TRX-06 | `Categorize Unknown Merchant transaction` | `TransactionCategorizerTool` | `Category: other` | Unmatched descriptions fall back to `other`. |

## Workflow and validation cases

| Case ID | Sample input or action | Expected tool / outcome | Expected final output pattern | Trace/tool notes |
| --- | --- | --- | --- | --- |
| WF-01 | `What is the weather in Toronto and calculate 25 * 3` | `WeatherMockTool` + `CalculatorTool` | Numbered two-part response | Two tools used in order. |
| WF-02 | `Categorize Starbucks transaction 45 CAD and convert to USD` | `TransactionCategorizerTool` + `CurrencyConverterTool` | `1. Category: dining` and `2. ... USD` | Combined finance pipeline. |
| WF-03 | `Convert "a and b" to uppercase and weather in Toronto and calculate 2+2` | Validation error | Too many subtasks | Browser and API validation should align. |
| WF-04 | `Summarize the latest stock market news` | Unsupported handled turn | Unsupported-task message | Must not crash. |
| WF-05 | Create 5 chats, then click `Start new chat` again | Validation limit | Thread limit message | New chat action must be blocked at `5`. |
| WF-06 | In one chat, save 3 tasks, then submit a 4th | Validation limit | Thread flow limit message | Composer and API should block a `4th` saved flow. |

## Sign-off checklist

- All `30` tool-specific cases executed
- All `6` workflow and validation cases executed
- No unexpected crashes or blank result cards observed
- Trace steps matched the selected tool or tools
- Any failures captured with screenshots and trace IDs
