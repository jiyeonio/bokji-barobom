import { Layout } from './components/Layout';
import { IconSprite } from './components/Icon';
import { useRoute } from './router';
import Home from './pages/Home';
import Results from './pages/Results';
import Watch from './pages/Watch';
import Guide from './pages/Guide';
import Agency from './pages/Agency';
import Policies from './pages/Policies';
import PolicyItem from './pages/PolicyItem';

export default function App() {
  const route = useRoute();
  const t = route.params.get('t');

  let page;
  switch (route.path) {
    case '/results':
      page = <Results query={route.params.get('q') || '기초연금 신청서 어떻게 써요?'} policyCtx={route.params.get('policy') || undefined} />;
      break;
    case '/watch':
      page = <Watch videoId={route.id || 'v1'} startAt={t ? Number(t) : undefined} endAt={route.params.get('e') ? Number(route.params.get('e')) : undefined} jobId={route.params.get('job') || undefined} tab={route.params.get('tab') || undefined} />;
      break;
    case '/policies':
      page = <Policies params={route.params} />;
      break;
    case '/policy':
      page = <PolicyItem id={route.id || ''} />;
      break;
    case '/agency':
      page = <Agency />;
      break;
    case '/guide':
      page = <Guide />;
      break;
    default:
      page = <Home />;
  }

  return (
    <>
      <IconSprite />
      <Layout current={route.path}>{page}</Layout>
    </>
  );
}
