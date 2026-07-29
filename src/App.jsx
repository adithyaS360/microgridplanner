import React, { useState } from 'react';
import axios from 'axios';
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Activity, Battery, Zap, DollarSign } from 'lucide-react';

const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444'];

function App() {
  const [formData, setFormData] = useState({
    lat: 10,
    lon: 10,
    load: 100,
    fuel_cost: 1.2,
    renewables_target: 0.8,
    autonomy_days: 1.0,
    load_factor: 0.6
  });
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: parseFloat(e.target.value) || e.target.value
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await axios.post('http://127.0.0.1:5000/api/plan', formData);
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  const costData = result ? [
    { name: 'PV', value: result.capex_pv },
    { name: 'Battery', value: result.capex_batt },
    { name: 'Inverter', value: result.capex_inv },
    { name: 'Generator', value: result.capex_gen }
  ] : [];

  const energyData = result ? [
    { name: 'PV/Batt', kWh: result.served_by_pv_batt },
    { name: 'Generator', kWh: result.served_by_gen }
  ] : [];

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6">
      <header className="max-w-6xl mx-auto mb-8">
        <h1 className="text-3xl font-bold text-teal-400 flex items-center gap-2">
          <Activity className="w-8 h-8" />
          Microgrid Feasibility Dashboard
        </h1>
        <p className="text-gray-400 mt-2">Plan and estimate the specifications and costs of a localized microgrid setup.</p>
      </header>

      <main className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Form Section */}
        <section className="bg-gray-800 p-6 rounded-xl shadow-lg border border-gray-700 h-fit">
          <h2 className="text-xl font-semibold mb-4 text-gray-200 border-b border-gray-700 pb-2">Location & Parameters</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Latitude</label>
                <input type="number" step="any" name="lat" value={formData.lat} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500" required />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Longitude</label>
                <input type="number" step="any" name="lon" value={formData.lon} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500" required />
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">Daily Load (kWh/day)</label>
              <input type="number" step="any" name="load" value={formData.load} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500" required />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">Fuel Cost (USD/L)</label>
              <input type="number" step="any" name="fuel_cost" value={formData.fuel_cost} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500" required />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Renewables Target</label>
                <select name="renewables_target" value={formData.renewables_target} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500">
                  <option value={0.6}>60%</option>
                  <option value={0.8}>80%</option>
                  <option value={0.95}>95%</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Autonomy (Days)</label>
                <select name="autonomy_days" value={formData.autonomy_days} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500">
                  <option value={0.5}>0.5 Days</option>
                  <option value={1.0}>1 Day</option>
                  <option value={2.0}>2 Days</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">Load Type (Factor)</label>
              <select name="load_factor" value={formData.load_factor} onChange={handleChange} className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-teal-500">
                <option value={0.6}>Village (0.6)</option>
                <option value={0.5}>Mine (0.5)</option>
                <option value={0.7}>Clinic (0.7)</option>
              </select>
            </div>

            <button type="submit" disabled={loading} className="w-full mt-4 bg-teal-600 hover:bg-teal-700 text-white font-bold py-3 px-4 rounded transition duration-200 flex justify-center items-center gap-2">
              {loading ? 'Calculating...' : (
                <>
                  <Zap className="w-5 h-5" /> Calculate Microgrid
                </>
              )}
            </button>

            {error && <div className="mt-4 p-3 bg-red-900/50 border border-red-500 text-red-200 rounded">{error}</div>}
          </form>
        </section>

        {/* Results Section */}
        {result && (
          <section className="lg:col-span-2 space-y-6">

            {/* KPI Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-800 p-4 rounded-xl border border-gray-700 flex flex-col justify-center items-center">
                <p className="text-gray-400 text-sm mb-1 text-center">Estimated LCOE</p>
                <p className="text-2xl font-bold text-teal-400 flex items-center"><DollarSign className="w-5 h-5" />{result.lcoe}/kWh</p>
              </div>
              <div className="bg-gray-800 p-4 rounded-xl border border-gray-700 flex flex-col justify-center items-center">
                <p className="text-gray-400 text-sm mb-1 text-center">Total CAPEX</p>
                <p className="text-2xl font-bold text-white flex items-center"><DollarSign className="w-5 h-5" />{result.capex_total.toLocaleString()}</p>
              </div>
              <div className="bg-gray-800 p-4 rounded-xl border border-gray-700 flex flex-col justify-center items-center">
                <p className="text-gray-400 text-sm mb-1 text-center">PV Capacity</p>
                <p className="text-2xl font-bold text-yellow-500">{result.pv_kw} kW</p>
              </div>
              <div className="bg-gray-800 p-4 rounded-xl border border-gray-700 flex flex-col justify-center items-center">
                <p className="text-gray-400 text-sm mb-1 text-center">Battery Storage</p>
                <p className="text-2xl font-bold text-blue-400 flex items-center gap-1"><Battery className="w-5 h-5"/> {result.batt_kwh} kWh</p>
              </div>
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

              {/* CAPEX Breakdown Pie Chart */}
              <div className="bg-gray-800 p-6 rounded-xl border border-gray-700">
                <h3 className="text-lg font-semibold text-gray-200 mb-4">CAPEX Breakdown (USD)</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={costData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                        {costData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value) => `$${value.toLocaleString()}`} contentStyle={{backgroundColor: '#1f2937', border: 'none', color: '#fff'}} />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Energy Mix Bar Chart */}
              <div className="bg-gray-800 p-6 rounded-xl border border-gray-700">
                <h3 className="text-lg font-semibold text-gray-200 mb-4">Energy Served (kWh/yr)</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={energyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
                      <XAxis dataKey="name" stroke="#9ca3af" />
                      <YAxis stroke="#9ca3af" />
                      <Tooltip formatter={(value) => `${value.toLocaleString()} kWh`} contentStyle={{backgroundColor: '#1f2937', border: 'none', color: '#fff'}} cursor={{fill: '#374151'}} />
                      <Bar dataKey="kWh" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Warnings */}
            {result.warnings && result.warnings.length > 0 && (
              <div className="bg-yellow-900/30 border border-yellow-600 p-4 rounded-xl">
                <h4 className="text-yellow-500 font-semibold mb-2">Analysis Notes</h4>
                <ul className="list-disc list-inside text-sm text-yellow-200/80 space-y-1">
                  {result.warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

          </section>
        )}
      </main>
    </div>
  );
}

export default App;
