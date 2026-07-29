import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';
import axios from 'axios';

jest.mock('axios');
jest.mock('react-leaflet', () => ({
  MapContainer: ({ children }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => <div>TileLayer</div>,
  Marker: () => <div>Marker</div>,
  useMapEvents: () => ({}),
}));

test('renders the form and handles analysis submission', async () => {
  axios.post.mockResolvedValueOnce({
    data: {
      capex_total: 485600, opex: 14600, payback_period: '20 yr', roi_20yr: -41, irr: 3, co2_avoided_t: 193.4,
      buildings: 15, system_capacity: 218.3, batt_kwh: 660, solar_irradiance: 5.42, wind_speed: 5.08,
      energy_mix: { Solar: 95, Wind: 3.7, Biomass: 1.2 },
      annual_generation: 386714, reliability: 100, meets_demand: 'Yes',
      cumulative_cashflow: [-485600, -450000, -400000]
    }
  });

  render(<App />);

  // Should render Map and Run Analysis button
  expect(screen.getByTestId('map-container')).toBeInTheDocument();

  const runButton = screen.getByRole('button', { name: /Run Analysis/i });
  expect(runButton).toBeInTheDocument();

  // Click the button
  fireEvent.click(runButton);

  // Then it should eventually render the Energy Analysis Report header
  await waitFor(() => {
    const titleElement = screen.getByText(/Energy Analysis Report/i);
    expect(titleElement).toBeInTheDocument();
  });
});
