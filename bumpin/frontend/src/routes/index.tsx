import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { Overview } from '@/screens/overview/Overview'
import { RiderNeeds } from '@/screens/riders/RiderNeeds'
import { TicketDetail } from '@/screens/riders/TicketDetail'
import { VendorProgress } from '@/screens/vendors/VendorProgress'
import { VendorDetail } from '@/screens/vendors/VendorDetail'
import { RunSheet } from '@/screens/schedule/RunSheet'
import { Equipment } from '@/screens/schedule/Equipment'
import { Upload } from '@/screens/upload/Upload'

/* One folder per build slice: overview, riders, vendors, schedule, upload.
   No two slices share a file, so they can be built in parallel. */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'riders', element: <RiderNeeds /> },
      { path: 'tickets/:ticketId', element: <TicketDetail /> },
      { path: 'vendors', element: <VendorProgress /> },
      { path: 'vendors/:vendorId', element: <VendorDetail /> },
      { path: 'runsheet', element: <RunSheet /> },
      { path: 'equipment', element: <Equipment /> },
      { path: 'upload', element: <Upload /> },
    ],
  },
], {
  // Opt in early so the v7 upgrade is a no-op and the console stays clean.
  // v7_startTransition is a RouterProvider prop, not a router option — it is
  // set in main.tsx.
  future: { v7_relativeSplatPath: true },
})
