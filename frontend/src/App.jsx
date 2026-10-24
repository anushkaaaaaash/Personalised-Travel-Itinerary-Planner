import AuthBoundary from './components/AuthBoundary.jsx';
import { BrowserRouter } from 'react-router-dom';
function App() { return <BrowserRouter><AuthBoundary /></BrowserRouter>; }
export default App;
