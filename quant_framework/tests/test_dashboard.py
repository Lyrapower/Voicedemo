from unittest.mock import MagicMock, patch

import pandas as pd


def test_dashboard_main_renders():
    import quant_framework.dashboard.app as app_module

    mock_df = pd.DataFrame(
        {
            "momentum_12_1_raw": [0.1, -0.1],
            "momentum_12_1_zscore": [1.0, -1.0],
            "book_to_market_raw": [0.5, 0.4],
            "book_to_market_zscore": [0.5, -0.5],
            "gross_profitability_raw": [0.2, 0.1],
            "gross_profitability_zscore": [0.2, -0.2],
            "low_vol_12m_raw": [-0.1, -0.2],
            "low_vol_12m_zscore": [0.3, -0.3],
            "combined_score": [2.0, -2.0],
            "rank": [1, 2],
        },
        index=["AAA", "BBB"],
    )

    with patch.object(app_module, "st") as mock_st:
        mock_st.session_state = {}
        mock_st.title = MagicMock()
        mock_st.caption = MagicMock()
        mock_st.sidebar = MagicMock()
        mock_st.date_input = MagicMock(return_value=app_module.most_recent_month_end())
        mock_st.selectbox = MagicMock(return_value="S&P 500")
        mock_st.slider = MagicMock(return_value=0.25)
        mock_st.button = MagicMock(return_value=False)
        mock_st.tabs = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
        mock_st.subheader = MagicMock()
        mock_st.dataframe = MagicMock()
        mock_st.selectbox = MagicMock(return_value="AAA")
        mock_st.json = MagicMock()
        mock_st.plotly_chart = MagicMock()
        mock_st.columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
        mock_st.divider = MagicMock()
        mock_st.metric = MagicMock()
        mock_st.warning = MagicMock()
        mock_st.info = MagicMock()

        with patch.object(app_module, "build_cache") as mock_cache_fn:
            cache = MagicMock()
            cache.db_size_bytes.return_value = 1024
            cache.last_fetch_time.return_value = None
            cache.list_signal_runs.return_value = pd.DataFrame()
            mock_cache_fn.return_value = cache

            with patch.object(app_module, "_list_runs", return_value=pd.DataFrame()):
                app_module.main()

    mock_st.title.assert_called()
