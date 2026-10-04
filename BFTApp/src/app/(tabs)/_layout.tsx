import { Tabs, useRouter } from 'expo-router';
import { useAuth } from '@clerk/expo';
import { useEffect, useState } from 'react';
import { View, ActivityIndicator } from 'react-native';

export default function TabLayout() {
  const { isLoaded, isSignedIn, user } = useAuth();
  const router = useRouter();
  const [hasOverlandPermission, setHasOverlandPermission] = useState<boolean | null>(null);

  useEffect(() => {
    if (isLoaded && isSignedIn && user) {
      checkOverlandPermission();
    }
  }, [isLoaded, isSignedIn, user]);

  const checkOverlandPermission = async () => {
    try {
      const response = await fetch(`${process.env.EXPO_PUBLIC_API_URL}/api/users/permissions/`);
      const data = await response.json();
      setHasOverlandPermission(data.overland || false);
    } catch (error) {
      console.error('Failed to check permissions:', error);
      setHasOverlandPermission(false);
    }
  };

  if (!isLoaded) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!isSignedIn) {
    router.replace('/sign-in');
    return null;
  }

  if (hasOverlandPermission === null) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!hasOverlandPermission) {
    router.replace('/access-denied');
    return null;
  }

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: '#444',
        tabBarInactiveTintColor: '#999',
        tabBarStyle: {
          backgroundColor: '#ffff9e',
          borderTopColor: '#de8',
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Tracking',
          tabBarIcon: ({ color }) => <TabIcon name="location" color={color} />,
        }}
      />
      <Tabs.Screen
        name="vehicles"
        options={{
          title: 'Vehicles',
          tabBarIcon: ({ color }) => <TabIcon name="bus" color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color }) => <TabIcon name="settings" color={color} />,
        }}
      />
    </Tabs>
  );
}

function TabIcon({ name, color }: { name: string; color: string }) {
  return <View style={{ width: 24, height: 24, backgroundColor: color }} />;
}
