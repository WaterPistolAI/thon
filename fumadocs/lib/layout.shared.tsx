import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { appName, gitConfig } from './shared';
import { NewspaperIcon,MessagesSquareIcon,BookOpenTextIcon } from 'lucide-react';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      // JSX supported
      title: appName,
    },
    links: [
      {
        icon: <BookOpenTextIcon />,
        text: 'Documentation',
        url: '/docs',
        // secondary items will be displayed differently on navbar
        secondary: false,
      },
      {
        icon: <NewspaperIcon />,
        text: 'Blog',
        url: 'https://waterpistol.co/blog',
        // secondary items will be displayed differently on navbar
        secondary: false,
      },
      {
        icon: <MessagesSquareIcon />,
        text: 'Discord',
        url: 'https://discord.waterpistol.co',
        // secondary items will be displayed differently on navbar
        secondary: false,
      },
    ],
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
  };
  
}