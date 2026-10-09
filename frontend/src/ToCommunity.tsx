import { Navigate, useLocation } from 'react-router-dom'

/** Every other address opens the Community. Older links (Community 0.3 invitations were
 *  /?invite=…) keep their query string. */
export function ToCommunity() {
  const { search } = useLocation()
  return <Navigate to={'/community' + search} replace />
}
