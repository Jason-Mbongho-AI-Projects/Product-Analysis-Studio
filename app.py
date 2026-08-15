"""Product Analysis Studio - entry point.

Run with:  streamlit run app.py

All logic lives in the ``pas`` package; this file only starts the UI.
"""

from pas.ui.app import main

if __name__ == "__main__":
    main()
