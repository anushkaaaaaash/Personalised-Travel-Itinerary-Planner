import { useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import PlannerForm from '../components/PlannerForm.jsx';
import ItineraryResults from '../components/ItineraryResults.jsx';
import { getHealth } from '../services/api.js';
import { buildPreviewItinerary } from '../utils/buildPreviewItinerary.js';

const initialForm = {
  destination: '',
  departureCity: '',
  startDate: '',
  endDate: '',
  travelers: 2,
  budget: 2500,
  currency: 'USD',
  interests: ['culture', 'food'],
};

function PlannerPage() {
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [itinerary, setItinerary] = useState(null);

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  function handleToggleInterest(id) {
    setForm((current) => {
      const exists = current.interests.includes(id);
      return {
        ...current,
        interests: exists
          ? current.interests.filter((item) => item !== id)
          : [...current.interests, id],
      };
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');
    setItinerary(null);

    if (form.endDate && form.startDate && form.endDate < form.startDate) {
      setError('End date must be on or after the start date.');
      return;
    }

    setLoading(true);

    try {
      await Promise.all([
        getHealth(),
        new Promise((resolve) => setTimeout(resolve, 700)),
      ]);
      setItinerary(buildPreviewItinerary(form));
    } catch {
      setError(
        'The planner service is not reachable. Start the backend and try again.'
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <SiteHeader />
      <main className="layout">
        <PlannerForm
          form={form}
          onChange={handleChange}
          onToggleInterest={handleToggleInterest}
          onSubmit={handleSubmit}
          loading={loading}
        />
        <ItineraryResults itinerary={itinerary} loading={loading} error={error} />
      </main>
    </div>
  );
}

export default PlannerPage;
