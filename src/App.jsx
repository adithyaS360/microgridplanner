import React, { useState } from 'react';
import axios from 'axios';
import {
  ArrowLeft, Calendar, TrendingUp, Leaf, Building2, Zap, Battery, Sun, Wind, DollarSign
} from 'lucide-react';
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend
} from 'recharts';

function App() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const [formData, setFormData] = useState({
    lat: 12.3829,
    lon: 77.3947,
    load: 1000,
    buildings: 15
  });

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: parseFloat(e.target.value) || e.target.value
    });
  };

  const handleRunAnalysis = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await axios.post('http://127.0.0.1:5000/api/plan', formData);
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    handleRunAnalysis();
  }, []); // Run once on mount

  const formatMoney = (val) => {
    if (!val) return '$0';
    if (Math.abs(val) >= 1000) {
      return `$${(val / 1000).toFixed(1)}K`;
    }
    return `$${val.toFixed(1)}`;
  };

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-800 font-sans flex flex-col">
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button className="flex items-center gap-2 text-slate-500 hover:text-slate-800 transition">
            <ArrowLeft className="w-4 h-4" />
            <span className="text-sm font-medium">New Analysis</span>
          </button>
          <div className="h-6 w-px bg-slate-300"></div>
          <div>
            <h1 className="text-lg font-bold text-slate-900 leading-tight">Energy Analysis Report</h1>
            <p className="text-xs text-slate-500">{formData.lat}°, {formData.lon}° - Configured</p>
          </div>
        </div>
        <div className="flex gap-2">
          <span className="px-3 py-1 bg-green-50 text-green-700 text-xs font-semibold rounded-full border border-green-200 flex items-center gap-1">
            <Sun className="w-3 h-3"/> nasa-power
          </span>
          <span className="px-3 py-1 bg-blue-50 text-blue-700 text-xs font-semibold rounded-full border border-blue-200 flex items-center gap-1">
            <Wind className="w-3 h-3"/> open-meteo
          </span>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto p-6 grid grid-cols-1 lg:grid-cols-4 gap-6 w-full">
        {/* Input Form */}
        <div className="lg:col-span-1 space-y-6">
            <form onSubmit={handleRunAnalysis} className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
              <h2 className="text-base font-bold text-slate-800">Parameters</h2>

              <div>
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Latitude</label>
                <input type="number" step="any" name="lat" value={formData.lat} onChange={handleChange} className="w-full bg-slate-50 border border-slate-200 rounded p-2 text-slate-800 text-sm focus:outline-none focus:border-blue-500" required />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Longitude</label>
                <input type="number" step="any" name="lon" value={formData.lon} onChange={handleChange} className="w-full bg-slate-50 border border-slate-200 rounded p-2 text-slate-800 text-sm focus:outline-none focus:border-blue-500" required />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Daily Load (kWh)</label>
                <input type="number" step="any" name="load" value={formData.load} onChange={handleChange} className="w-full bg-slate-50 border border-slate-200 rounded p-2 text-slate-800 text-sm focus:outline-none focus:border-blue-500" required />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Buildings</label>
                <input type="number" name="buildings" value={formData.buildings} onChange={handleChange} className="w-full bg-slate-50 border border-slate-200 rounded p-2 text-slate-800 text-sm focus:outline-none focus:border-blue-500" required />
              </div>

              <button type="submit" disabled={loading} className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded text-sm transition duration-200 flex justify-center items-center gap-2">
                {loading ? 'Calculating...' : 'Run Analysis'}
              </button>
            </form>
            {error && <div className="p-4 text-red-600 bg-red-50 border border-red-200 rounded-xl text-sm">{error}</div>}
        </div>

        {/* Results Area */}
        <div className="lg:col-span-3 space-y-6">
          {!result && !error && (
             <div className="p-8 text-slate-500 font-bold bg-white rounded-xl text-center border border-slate-200 shadow-sm">
                Enter parameters and run analysis.
             </div>
          )}

          {result && (
            <>
              {/* Top 4 KPI Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-orange-50/50 border border-orange-200 rounded-xl p-5 flex flex-col justify-between relative shadow-sm">
                  <div className="text-xs font-bold text-orange-400 uppercase tracking-wider mb-2">Total Investment</div>
                  <div className="text-3xl font-extrabold text-orange-700">{formatMoney(result.capex_total)}</div>
                  <div className="text-xs text-orange-600/80 mt-1">OPEX: {formatMoney(result.opex)}/yr</div>
                  <DollarSign className="w-5 h-5 text-orange-300 absolute top-4 right-4" />
                </div>
                <div className="bg-emerald-50/50 border border-emerald-200 rounded-xl p-5 flex flex-col justify-between relative shadow-sm">
                  <div className="text-xs font-bold text-emerald-400 uppercase tracking-wider mb-2">Payback Period</div>
                  <div className="text-3xl font-extrabold text-emerald-700">{result.payback_period}</div>
                  <div className="text-xs text-emerald-600/80 mt-1">Beyond 20 yr</div>
                  <Calendar className="w-5 h-5 text-emerald-300 absolute top-4 right-4" />
                </div>
                <div className="bg-blue-50/50 border border-blue-200 rounded-xl p-5 flex flex-col justify-between relative shadow-sm">
                  <div className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-2">20-Year ROI</div>
                  <div className="text-3xl font-extrabold text-blue-700">{result.roi_20yr?.toFixed(0)}%</div>
                  <div className="text-xs text-blue-600/80 mt-1">IRR: {result.irr?.toFixed(0)}%</div>
                  <TrendingUp className="w-5 h-5 text-blue-300 absolute top-4 right-4" />
                </div>
                <div className="bg-purple-50/50 border border-purple-200 rounded-xl p-5 flex flex-col justify-between relative shadow-sm">
                  <div className="text-xs font-bold text-purple-400 uppercase tracking-wider mb-2">CO2 Avoided / Yr</div>
                  <div className="text-3xl font-extrabold text-purple-700">{result.co2_avoided_t?.toFixed(1)} t</div>
                  <div className="text-xs text-purple-600/80 mt-1">≈ {(result.co2_avoided_t * 50).toFixed(0)} trees</div>
                  <Leaf className="w-5 h-5 text-purple-300 absolute top-4 right-4" />
                </div>
              </div>

              {/* Info Strip */}
              <div className="bg-white border border-slate-200 rounded-xl p-4 grid grid-cols-2 md:grid-cols-5 gap-4 shadow-sm">
                <div className="flex items-center gap-3 border-r border-slate-100 last:border-0 pr-4">
                  <Building2 className="w-6 h-6 text-slate-400" />
                  <div>
                    <div className="text-[10px] text-slate-400 uppercase font-bold">Buildings</div>
                    <div className="font-semibold text-slate-700">{result.buildings}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 border-r border-slate-100 last:border-0 pr-4">
                  <Zap className="w-6 h-6 text-slate-400" />
                  <div>
                    <div className="text-[10px] text-slate-400 uppercase font-bold">System Capacity</div>
                    <div className="font-semibold text-slate-700">{result.system_capacity} kW</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 border-r border-slate-100 last:border-0 pr-4">
                  <Battery className="w-6 h-6 text-slate-400" />
                  <div>
                    <div className="text-[10px] text-slate-400 uppercase font-bold">Battery Storage</div>
                    <div className="font-semibold text-slate-700">{result.batt_kwh} kWh</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 border-r border-slate-100 last:border-0 pr-4">
                  <Sun className="w-6 h-6 text-slate-400" />
                  <div>
                    <div className="text-[10px] text-slate-400 uppercase font-bold">Solar Irradiance</div>
                    <div className="font-semibold text-slate-700">{result.solar_irradiance} kWh/m²</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Wind className="w-6 h-6 text-slate-400" />
                  <div>
                    <div className="text-[10px] text-slate-400 uppercase font-bold">Wind Speed</div>
                    <div className="font-semibold text-slate-700">{result.wind_speed} m/s</div>
                  </div>
                </div>
              </div>

              {/* Main Charts */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                {/* Energy Mix Chart */}
                <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm flex flex-col h-[400px]">
                  <div className="flex items-center gap-2 mb-1">
                    <TrendingUp className="w-4 h-4 text-slate-400"/>
                    <h2 className="text-base font-bold text-slate-800">Recommended Energy Mix</h2>
                  </div>
                  <p className="text-xs text-slate-500 mb-6">Optimal renewable allocation for this site</p>

                  <div className="flex-1 min-h-0 w-full relative">
                    {result.energy_mix && (
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={[
                              { name: 'Solar', value: result.energy_mix.Solar, fill: '#f59e0b' },
                              { name: 'Wind', value: result.energy_mix.Wind, fill: '#3b82f6' },
                              { name: 'Biomass', value: result.energy_mix.Biomass, fill: '#22c55e' }
                            ]}
                            cx="50%" cy="50%"
                            innerRadius="60%" outerRadius="80%"
                            paddingAngle={2}
                            dataKey="value"
                          >
                            <Cell fill="#f59e0b" />
                            <Cell fill="#3b82f6" />
                            <Cell fill="#22c55e" />
                          </Pie>
                          <RechartsTooltip formatter={(value) => `${value}%`} />
                          <Legend verticalAlign="bottom" height={36}/>
                        </PieChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-slate-100 flex-none">
                    <div className="text-center">
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Annual Generation</div>
                      <div className="font-semibold text-slate-800">{result.annual_generation?.toLocaleString()} kWh</div>
                    </div>
                    <div className="text-center">
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Reliability</div>
                      <div className="font-semibold text-slate-800">{result.reliability}%</div>
                    </div>
                    <div className="text-center">
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Meets Demand</div>
                      <div className="font-semibold text-slate-800">{result.meets_demand}</div>
                    </div>
                  </div>
                </div>

                {/* Cashflow Chart */}
                <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm flex flex-col h-[400px]">
                  <div className="flex items-center gap-2 mb-1">
                    <DollarSign className="w-4 h-4 text-slate-400"/>
                    <h2 className="text-base font-bold text-slate-800">20-Year Cumulative Cashflow</h2>
                  </div>
                  <p className="text-xs text-slate-500 mb-6">Investment recovery over project lifetime</p>

                  <div className="flex-1 min-h-0 w-full">
                    {result.cumulative_cashflow && (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={result.cumulative_cashflow.map((val, idx) => ({ year: idx, value: val }))} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                          <defs>
                            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#10b981" stopOpacity={0.4}/>
                              <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                          <XAxis dataKey="year" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} />
                          <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{fill: '#64748b', fontSize: 12}}
                            tickFormatter={(val) => {
                              if (val === 0) return '0';
                              return `${val > 0 ? '' : '-'}$${Math.abs(val)/1000}K`;
                            }}
                          />
                          <RechartsTooltip
                            formatter={(val) => `$${val.toLocaleString()}`}
                            labelFormatter={(label) => `Year ${label}`}
                          />
                          <Area
                            type="monotone"
                            dataKey="value"
                            stroke="#10b981"
                            strokeWidth={2}
                            fillOpacity={1}
                            fill="url(#colorValue)"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>

              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
