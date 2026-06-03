interface Project {
    id: string;
    name: string;
}
interface NavigationProps {
    currentProject: Project | null;
}
declare const Navigation: ({ currentProject }: NavigationProps) => import("react/jsx-runtime").JSX.Element;
export default Navigation;
