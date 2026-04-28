import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the main application title', () => {
  render(<App />);
  
  // We look for the main title of your application, which is present in the rendered output.
  const titleElement = screen.getByText(/Microgrid Feasibility Planner/i);
  
  expect(titleElement).toBeInTheDocument();
});

test('renders the Analyze Coordinates button', () => {
    render(<App />);
    
    // Check for a key interactive element to ensure the UI loaded correctly
    const analyzeButton = screen.getByRole('button', { name: /Analyze Coordinates/i });
    
    expect(analyzeButton).toBeInTheDocument();
});
