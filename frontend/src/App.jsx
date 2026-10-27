import AuthBoundary from './components/AuthBoundary.jsx';
import { DestinationThemeProvider } from './themes/DestinationTheme.jsx';
import { BrowserRouter } from 'react-router-dom';
function App() { return <DestinationThemeProvider><BrowserRouter><AuthBoundary /></BrowserRouter></DestinationThemeProvider>; }
export default App;
