import { createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

export default function MarketChart({ data }) {
  const chartRef = useRef(null);
  const seriesRef = useRef(null);

  useEffect(() => {
    if (!chartRef.current) {
      chartRef.current = createChart(document.getElementById("market-chart"), {
        height: 280,
        layout: { textColor: "#e6e6e6", background: { type: "solid", color: "#0f172a" } },
        grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } }
      });
      seriesRef.current = chartRef.current.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444"
      });
    }

    if (seriesRef.current && data?.length) {
      const transformed = data.map((k) => ({
        time: Math.floor(k.open_time / 1000),
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close
      }));
      seriesRef.current.setData(transformed);
      chartRef.current.timeScale().fitContent();
    }
  }, [data]);

  return <div id="market-chart" className="chart" />;
}
