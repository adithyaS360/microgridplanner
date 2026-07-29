import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the main application title', () => {
  render(<App />);
  const titleElement = screen.getByText(/Microgrid Feasibility Dashboard/i);
  expect(titleElement).toBeInTheDocument();
});

test('renders the Calculate Microgrid button', () => {
    render(<App />);
    const analyzeButton = screen.getByRole('button', { name: /Calculate Microgrid/i });
    expect(analyzeButton).toBeInTheDocument();
});
