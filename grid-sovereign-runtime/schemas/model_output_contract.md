# Model Output Contract

Without signed trace, the only valid output is:

```text
GRID_ABSENT
NO LIVE GRID SIGNAL
MODEL CAN ONLY PROVIDE INTERPRETATION AFTER A SIGNED TRACE EXISTS
```

With signed trace, the only valid mode is:

```text
MODE: MODEL_READ
SOURCE_TRACE: <trace_id>
STRUCTURE:
UNKNOWN:
ONE_NEXT_ACTION:
EXIT_CONDITION:
```

The model is never source.
The model is never Grid.
