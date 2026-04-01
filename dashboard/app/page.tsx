import LiveStatus from "@/components/LiveStatus";
import EquityCurve from "@/components/EquityCurve";
import LevelTracker from "@/components/LevelTracker";
import StatsGrid from "@/components/StatsGrid";
import RecentTrades from "@/components/RecentTrades";
import AssetBreakdown from "@/components/AssetBreakdown";
import RegimeIndicator from "@/components/RegimeIndicator";
import WhaleActivity from "@/components/WhaleActivity";

export default function Dashboard() {
  return (
    <main className="max-w-6xl mx-auto px-4 py-8 space-y-6">
      <LiveStatus />
      <EquityCurve />
      <LevelTracker />
      <StatsGrid />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <AssetBreakdown />
        <div className="space-y-6">
          <RegimeIndicator />
          <WhaleActivity />
        </div>
      </div>

      <RecentTrades />

      <footer className="text-center text-muted text-xs py-8 border-t border-card-border">
        <p>Built by @adoniscyril | Zima Blue Media</p>
        <p className="mt-1">
          This is a trading experiment, not financial advice.
        </p>
      </footer>
    </main>
  );
}
